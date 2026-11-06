"""Build the pinned kernel release and its source-built prerequisites."""
from contextlib import contextmanager
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import time
import tomllib
import urllib.error
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ElementTree

from bootstrap import KIT, BootstrapError, run


def write_changed(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def merge_version_index(source, target):
    """Add source's versions to target's index and make source's release the latest."""
    merged = ElementTree.parse(target)
    versioning = merged.getroot().find('versioning')
    new = ElementTree.parse(source).getroot().find('versioning')
    listed = versioning.find('versions')
    known = {version.text for version in listed}
    for version in new.find('versions'):
        if version.text not in known:
            ElementTree.SubElement(listed, 'version').text = version.text
    for tag in ['latest', 'release', 'lastUpdated']:
        versioning.find(tag).text = new.find(tag).text
    ElementTree.indent(merged, '  ')
    merged.write(target, xml_declaration=True, encoding='UTF-8')


# Committed locks name this loopback address; each run rebinds it to its own registry.
LOCK_REGISTRY = 'http://127.0.0.1:4873/'
METAMODEL_ARTIFACT = re.compile(r'mm(typings|dmjsons|validators)-[a-z0-9_.-]+')


def kernel_metamodels(kernel):
    """List the metamodel artifacts the kernel build depends on, at its catalog versions.

    Only referenced catalog entries count: the kernel catalog also names metamodels
    (e.g. MM_Package) that no kernel module uses and the public export does not contain.
    """
    catalog = tomllib.loads((kernel / 'gradle/libs.versions.toml').read_text())
    scripts = '\n'.join(path.read_text() for path in kernel.rglob('*.gradle') if path.is_file()
                        and not {'node_modules', '.gradle', 'build'} & set(path.relative_to(kernel).parts[:-1]))
    referenced = set(re.findall(r'\blibs\.([A-Za-z0-9]+)\b', scripts))
    found = {}
    for alias, library in catalog['libraries'].items():
        if isinstance(library, str):  # "group:artifact:version" shorthand
            library = dict(zip(['group', 'name', 'version'], library.split(':')))
        elif 'module' in library:
            library = library | dict(zip(['group', 'name'], library['module'].split(':')))
        version = library.get('version')
        if isinstance(version, dict):
            version = catalog['versions'][version['ref']]
        if alias in referenced and library['group'] == 'com.mgmtp.a12.kernel' and METAMODEL_ARTIFACT.fullmatch(library['name']):
            found[library['name']] = version
    for artifact, version in re.findall(r'["\']com\.mgmtp\.a12\.kernel:(mm(?:typings|dmjsons|validators)-[a-z0-9_.-]+):([^"\']+)["\']', scripts):
        found[artifact] = version
    return [{'artifact': artifact, 'version': found[artifact], 'kind': METAMODEL_ARTIFACT.fullmatch(artifact)[1]}
            for artifact in sorted(found)]


def add_overrides(workspace, additions):
    """Put additions first in pnpm-workspace.yaml's overrides block, at the block's own indentation."""
    block = re.search(r'^overrides:\n([ \t]+)', workspace, flags=re.M)
    indent = block[1] if block else '  '
    entries = ''.join(f'{indent}{name}: {version}\n' for name, version in additions.items())
    if block:
        return workspace[:block.start(1)] + entries + workspace[block.start(1):]
    return workspace + '\noverrides:\n' + entries


class ReleaseBuilder:
    def __init__(self, state, release, gradle, env):
        self.state, self.release, self.gradle, self.env = state, release, gradle, env.copy()
        self.sources = state / 'sources'
        self.logs = state / 'logs'
        self.logs.mkdir(exist_ok=True)
        self.artifacts = state / 'npm-artifacts'
        self.artifacts.mkdir(exist_ok=True)
        self.local_integrity = {}  # (package name, version) -> integrity of the tarball packed in this run
        for variable, repo in [('A12_KERNEL_DIR', 'a12-kernel'), ('A12_MM_DIR', 'a12-kernel-mm'),
                               ('A12_WCF_DIR', 'a12-dataservices-wcf')]:
            self.env[variable] = str(self.sources / repo)

    def stage(self, label, args, cwd=None, env=None):
        log = self.logs / (label + '.log')
        print(f'[{label}] {log}', flush=True)
        with log.open('w') as output:
            result = subprocess.run(list(map(str, args)), cwd=cwd, env=env or self.env,
                                    stdout=output, stderr=subprocess.STDOUT)
        if result.returncode:
            print('\n'.join(log.read_text(errors='replace').splitlines()[-70:]), flush=True)
            raise BootstrapError(f'{label} failed ({result.returncode}); full output: {log}')
        print(f'[{label}] completed', flush=True)

    def java(self, label, directory, *tasks, env=None):
        self.stage(label, self.gradle + ['-p', directory, *tasks], env=env)

    def original(self, repo, filename):
        return run(['git', f'--git-dir={self.state / "git" / (repo + ".git")}',
                    'show', f'{self.release["repositories"][repo]}:{filename}'], capture=True) + '\n'

    def prepare_java(self):
        for name in ['java', 'wcf', 'smoke']:
            target = self.state / (name + '-bootstrap')
            for source in (KIT / 'build-support' / name).rglob('*'):
                if source.is_file():
                    write_changed(target / source.relative_to(KIT / 'build-support' / name), source.read_text())
        kernel = self.sources / 'a12-kernel'
        self.specs = kernel_metamodels(kernel)
        write_changed(self.state / 'java-bootstrap/metamodels.json', json.dumps(self.specs, indent=2) + '\n')
        for name in ['typed-generator', 'validator-generator'] + [s['artifact'] for s in self.specs]:
            (self.state / 'java-bootstrap' / name).mkdir(exist_ok=True)
        # The bootstrap Gradle builds take every version from the manifest or the
        # kernel catalog, so a release upgrade does not edit them.
        catalog = tomllib.loads((kernel / 'gradle/libs.versions.toml').read_text())
        self.runtime = catalog['libraries']['a12KernelRuntimeArtifactId']['module'].split(':')[1]
        self.env |= {'A12_KERNEL_VERSION': self.release['kernel_version'],
                     'A12_KERNEL_RUNTIME': self.runtime,
                     'A12_BASE_VERSION': self.release['base_version'],
                     'A12_RUNTIME_API_VERSION': self.release['runtime_api_version'],
                     'A12_WCF_API_VERSION': self.release['wcf_api_version']}

    def build_java_dependencies(self):
        self.prepare_java()
        self.java('devtools-java', self.sources / 'a12-devtools',
                  ':gradle-plugins:build-utilities:build', ':gradle-plugins:integration:build',
                  ':gradle-plugins:build-utilities:publishToMavenLocal',
                  ':gradle-plugins:integration:publishToMavenLocal')
        base_modules = ['base-bom', 'model-api', 'model-consistency', 'model-marshalling',
                        'model-utils', 'fs-model-repository']
        self.java('base-java', self.sources / 'a12-base',
                  *[f':{module}:{task}' for module in base_modules for task in ['build', 'publishToMavenLocal']])
        self.java('wcf-api', self.state / 'wcf-bootstrap', 'build', 'publishToMavenLocal')
        self.java('metamodel-build-logic', self.sources / 'a12-kernel-mm/build-logic', 'jar')
        self.java('metamodel-types', self.state / 'java-bootstrap',
                  *[':' + s['artifact'] + ':publishToMavenLocal' for s in self.specs if s['kind'] != 'validators'])
        seed_env = self.env | {'A12_KERNEL_BOOTSTRAP_VALIDATORS_DISABLE_MM_VALIDATION': 'true'}
        common = next(s for s in self.specs if s['artifact'] == 'mmvalidators-extmpinternal-mm_common-v2-codegen')
        common_jar = (self.state / 'maven/com/mgmtp/a12/kernel' / common['artifact'] / common['version']
                      / f"{common['artifact']}-{common['version']}.jar")
        task = f":{common['artifact']}:publishToMavenLocal"
        if not common_jar.exists():
            self.java('common-validator-seed', self.state / 'java-bootstrap', task, env=seed_env)
        # This second pass is mandatory: validation is enabled and the generated
        # validator must successfully validate the input to its own generator.
        self.java('common-validator-validated', self.state / 'java-bootstrap', task)
        self.java('metamodel-validators', self.state / 'java-bootstrap',
                  *[':' + s['artifact'] + ':publishToMavenLocal' for s in self.specs if s['kind'] == 'validators'])
        self.java('runtime-publications', self.sources / 'a12-kernel',
                  *[':' + name + ':publishToMavenLocal' for name in ['kernel-core-customfieldtype-api',
                    'kernel-core-runtime-api', 'kernel-conversion-java', self.runtime]])

    def install_tool(self, package, version, binary):
        prefix = self.state / 'tools' / f'{package}-{version}'
        executable = prefix / 'node_modules/.bin' / binary
        if not executable.exists():
            self.stage('install-' + package, ['npm', 'install', '--prefix', prefix, '--no-audit',
                                             '--no-fund', f'{package}@{version}'])
        return executable

    @contextmanager
    def registry(self):
        executable = self.install_tool('verdaccio', '7.0.2', 'verdaccio')
        directory = self.state / 'registry'
        directory.mkdir(exist_ok=True)
        port_file = directory / 'port'
        if port_file.exists():
            port = int(port_file.read_text())
        else:
            with socket.socket() as connection:
                connection.bind(('127.0.0.1', 0))
                port = connection.getsockname()[1]
            port_file.write_text(str(port))
        # Fail if another process owns the address; never publish to an unknown server.
        with socket.socket() as connection:
            connection.bind(('127.0.0.1', port))
        self.registry_url = f'http://127.0.0.1:{port}/'
        write_changed(directory / 'config.yaml', '''storage: ./storage
auth:
  htpasswd:
    file: ./htpasswd
packages:
  '@com.mgmtp.a12*/*':
    access: $all
    publish: $authenticated
log: {type: stdout, format: pretty, level: warn}
''')
        with (self.logs / 'registry.log').open('w') as output:
            process = subprocess.Popen([str(executable), '--config', str(directory / 'config.yaml'),
                                        '--listen', f'127.0.0.1:{port}'], env=self.env,
                                       stdout=output, stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise BootstrapError('Local registry exited; see logs/registry.log')
                    try:
                        with urllib.request.urlopen(self.registry_url + '-/ping', timeout=1):
                            break
                    except (OSError, urllib.error.URLError):
                        time.sleep(.2)
                else:
                    raise BootstrapError('Local registry did not become ready')
                user = 'bootstrap-' + secrets.token_hex(8)
                request = urllib.request.Request(self.registry_url + '-/user/org.couchdb.user:' + user,
                    data=json.dumps({'name': user, 'password': secrets.token_urlsafe(32)}).encode(),
                    headers={'Content-Type': 'application/json'}, method='PUT')
                token = json.load(urllib.request.urlopen(request))['token']
                npmrc = 'registry=https://registry.npmjs.org/\n'
                for scope in ['devtools', 'utils', 'base', 'antlrcodeeditor', 'kernel', 'kernel.antlr4']:
                    npmrc += f'@com.mgmtp.a12.{scope}:registry={self.registry_url}\n'
                npmrc += f'//127.0.0.1:{port}/:_authToken={token}\n'
                config = directory / 'npmrc'
                config.write_text(npmrc)
                config.chmod(0o600)
                self.env['npm_config_userconfig'] = str(config)
                yield
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    def prepare_workspace(self, repo, packages):
        root = self.sources / repo
        package = json.loads(self.original(repo, 'package.json'))
        # Auxiliary docs/codemods are separate products, not kernel dependencies.
        # Keep each selected package's actual dependencies and native build scripts.
        package['devDependencies'] = {}
        package['scripts'] = {}
        package['packageManager'] = 'pnpm@' + self.pnpm_version(repo)
        write_changed(root / 'package.json', json.dumps(package, indent=2) + '\n')
        workspace = self.original(repo, 'pnpm-workspace.yaml')
        workspace = re.sub(r'packages:\n(?:[ \t].*\n|\n)*',
                           'packages:\n' + ''.join('  - ' + p + '\n' for p in packages) + '\n', workspace, count=1)
        # These upstream patches target unrelated editor examples / ESLint tools,
        # which are not in this dependency workspace.
        workspace = re.sub(r'patchedDependencies:\n(?:[ \t].*\n|\n)*', '', workspace)
        additions = {'semver': '7.8.5', 'chokidar': '4.0.1'}
        if repo == 'a12-antlr4-code-editor':
            additions["'@com.mgmtp.a12.devtools/tsconfig'"] = '2.0.1'
        workspace = add_overrides(workspace, additions)
        write_changed(root / 'pnpm-workspace.yaml', workspace)
        lock = KIT / 'build-support/locks' / repo / 'pnpm-lock.yaml'
        if lock.exists():
            write_changed(root / 'pnpm-lock.yaml', self.localize_lock(lock))
        elif (root / 'pnpm-lock.yaml').exists() and not (root / '.bootstrap-workspace').exists():
            (root / 'pnpm-lock.yaml').rename(root / 'pnpm-lock.yaml.upstream')
        (root / '.bootstrap-workspace').touch()
        locked = lock.exists()
        self.stage(repo + '-install', [self.pnpm(repo), 'install', '--config.manage-package-manager-versions=false',
                   '--frozen-lockfile' if locked else '--no-frozen-lockfile'], cwd=root)
        if not locked:
            self.record_lock(root / 'pnpm-lock.yaml', lock)

    def record_lock(self, resolved, kept):
        """Keep a freshly resolved lock in the kit; deleting a kit lock is how a release refreshes it."""
        write_changed(kept, resolved.read_text().replace(self.registry_url, LOCK_REGISTRY))
        print(f'Recorded new lock {kept}; review and commit it', flush=True)

    def localize_lock(self, path):
        # The committed loopback address is a placeholder, not a hosted registry.
        # A12 packages behind it are packed by this run, and their gzip bytes are
        # platform dependent (the header alone records the OS), so a hash recorded
        # on the lock author's machine cannot match. Bind those entries to the
        # tarballs built here; every third-party integrity stays locked.
        text = path.read_text().replace(LOCK_REGISTRY, self.registry_url)

        def built(name, version):
            try:
                return self.local_integrity[(name, version)]
            except KeyError:
                raise BootstrapError(f'{path} locks {name}@{version}, which this run has not built') from None

        if path.name == 'package-lock.json':
            lock = json.loads(text)
            for key, entry in lock['packages'].items():
                if entry.get('resolved', '').startswith(self.registry_url):
                    name = entry.get('name', key.rsplit('node_modules/', 1)[-1])
                    entry['integrity'] = built(name, entry['version'])
            return json.dumps(lock, indent=2, ensure_ascii=False) + '\n'
        return re.sub(r"^(  '(@com\.mgmtp\.a12\.[^@']+)@([^'(]+)':\n    resolution: \{integrity: )[^,}]+",
                      lambda m: m[1] + built(m[2], m[3]), text, flags=re.M)

    def package(self, repo, package, pnpm=True):
        root = self.sources / repo
        self.stage(repo + '-' + package.replace('/', '-') + '-pack',
                   [self.pnpm(repo), '--filter', './' + package, 'pack', '--pack-destination', self.artifacts]
                   if pnpm else ['npm', 'pack', '--pack-destination', self.artifacts],
                   cwd=root if pnpm else root / package)
        data = json.loads((root / package / 'package.json').read_text())
        tarball = self.artifacts / (data['name'].lstrip('@').replace('/', '-') + '-' + data['version'] + '.tgz')
        integrity = 'sha512-' + base64.b64encode(hashlib.sha512(tarball.read_bytes()).digest()).decode()
        self.local_integrity[(data['name'], data['version'])] = integrity
        url = self.registry_url + urllib.parse.quote(data['name'], safe='@') + '/' + data['version']
        try:
            published = json.load(urllib.request.urlopen(url))
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
        else:
            if published['dist']['integrity'] != integrity:
                raise BootstrapError(f'Local artifact {data["name"]} changed; use a fresh --home to avoid stale packages')
            return
        self.stage(repo + '-' + package.replace('/', '-') + '-publish-local',
                   ['npm', 'publish', tarball, '--registry', self.registry_url, '--tag', 'bootstrap'])

    def pnpm_version(self, repo):
        return self.release.get('pnpm_overrides', {}).get(repo, self.release['pnpm_version'])

    def pnpm(self, repo):
        """The pinned pnpm for one repository's workspace (see pnpm_overrides in the manifest)."""
        return self.install_tool('pnpm', self.pnpm_version(repo), 'pnpm')

    def provision_pnpm(self):
        # Java stages need pnpm too: the devtools integration plugin's tests run
        # `pnpm list` from PATH, and hosted CI runners carry no pnpm of their own.
        # Its plugins are the PATH consumer, so they get devtools' own pnpm major.
        self.env['PATH'] = str(self.pnpm('a12-devtools').parent) + os.pathsep + self.env['PATH']
        self.env['npm_config_manage_package_manager_versions'] = 'false'
        # pnpm 11+ reads pnpm_config_* (not npm_config_*). Setting the store for every
        # call keeps `pnpm run`/`pack` from relinking node_modules from the user's store.
        self.env['pnpm_config_store_dir'] = str(self.state / 'pnpm-store')

    def build_typescript_dependencies(self):
        packages = ['packages/build-tools', 'packages/eslint-config', 'packages/prettier-config', 'packages/tsconfig']
        self.prepare_workspace('a12-devtools', packages)
        self.stage('devtools-ts-compile', [self.pnpm('a12-devtools'), '-r', 'run', 'compile'], cwd=self.sources / 'a12-devtools')
        self.stage('devtools-ts-test', [self.pnpm('a12-devtools'), '--filter', './packages/build-tools', 'test'], cwd=self.sources / 'a12-devtools')
        for package in packages:
            self.package('a12-devtools', package)
        for repo, package, script in [('a12-utils', 'collections', 'build'), ('a12-logging', 'core', 'build'),
                ('a12-localization', 'localization', 'build'), ('a12-base', 'model-api-ts', 'build')]:
            self.prepare_workspace(repo, [package])
            for task in [script, 'test']:
                self.stage(repo + '-ts-' + task, [self.pnpm(repo), '--filter', './' + package, 'run', task], cwd=self.sources / repo)
            self.package(repo, package)
        antlr = self.sources / 'a12-kernel-antlr4/runtime/JavaScript'
        self.stage('antlr-install', ['npm', 'ci', '--no-audit', '--no-fund'], cwd=antlr)
        for task in ['build', 'test']:
            self.stage('antlr-' + task, ['npm', 'run', task], cwd=antlr)
        self.package('a12-kernel-antlr4', 'runtime/JavaScript', pnpm=False)
        self.prepare_workspace('a12-antlr4-code-editor', ['antlrcodeeditor-core'])
        for task in ['prepare-lib:gen', 'prepare-lib:correct', 'build', 'test']:
            self.stage('editor-' + task.replace(':', '-'), [self.pnpm('a12-antlr4-code-editor'), '--filter', './antlrcodeeditor-core', 'run', task],
                       cwd=self.sources / 'a12-antlr4-code-editor')
        self.package('a12-antlr4-code-editor', 'antlrcodeeditor-core')

    def build(self):
        ready = self.state / 'build-success.json'
        ready.unlink(missing_ok=True)
        if self.env.get('A12_KERNEL_BOOTSTRAP_VALIDATORS_DISABLE_MM_VALIDATION'):
            raise BootstrapError('Unset A12_KERNEL_BOOTSTRAP_VALIDATORS_DISABLE_MM_VALIDATION; only the initial seed may use it')
        self.provision_pnpm()
        self.build_java_dependencies()
        with self.registry():
            self.build_typescript_dependencies()
            kernel_lock = KIT / 'build-support/locks/a12-kernel/package-lock.json'
            if kernel_lock.exists():
                write_changed(self.sources / 'a12-kernel/package-lock.json', self.localize_lock(kernel_lock))
                self.stage('kernel-locked-install', ['npm', 'ci', '--no-audit', '--no-fund'], cwd=self.sources / 'a12-kernel')
            else:
                self.stage('kernel-install', ['npm', 'install', '--no-audit', '--no-fund'], cwd=self.sources / 'a12-kernel')
                self.record_lock(self.sources / 'a12-kernel/package-lock.json', kernel_lock)
            # --continue reports every failing module at once; the stage still fails.
            self.java('kernel-full-build', self.sources / 'a12-kernel', '-I', KIT / 'build-support/kernel-projects.init.gradle',
                      '--continue', 'build', 'test', 'publishToMavenLocal', 'npm_pack')
            self.java('java-release-smoke', self.state / 'smoke-bootstrap', 'run')
            self.check_typescript_artifacts()
        ready.write_text(json.dumps({'release': self.release, 'maven': str(self.state / 'maven'),
                                     'npm': str(self.artifacts)}, indent=2) + '\n')
        print(f'Full release build completed: {ready}', flush=True)
        self.install_maven_local(Path.home() / '.m2' / 'repository')

    def install_maven_local(self, repository):
        # The build resolves its own stages through an isolated mavenLocal so a
        # foreign or stale jar in ~/.m2 cannot stand in for a from-source stage.
        # Consumers still expect ~/.m2, so install the verified output the way
        # publishToMavenLocal does: replace these coordinates, keep every other
        # version, and merge each artifact's version index instead of replacing it.
        built = self.state / 'maven'
        for source in sorted(path for path in built.rglob('*') if path.is_file()):
            target = repository / source.relative_to(built)
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.name == 'maven-metadata-local.xml' and target.exists():
                merge_version_index(source, target)
            else:
                shutil.copy2(source, target)
        print(f'Installed the release Maven artifacts into {repository}', flush=True)

    def check_typescript_artifacts(self):
        kernel_packages = sorted((self.sources / 'a12-kernel').glob('**/build/libs/*.tgz'))
        if len(kernel_packages) != 5:
            raise BootstrapError(f'Expected five kernel TypeScript packages, found {len(kernel_packages)}')
        for artifact in kernel_packages:
            shutil.copy2(artifact, self.artifacts / artifact.name)
        smoke = self.state / 'npm-smoke'
        # Install the tarballs as an independent consumer. Do not let workspace
        # links or a previous installation hide broken package exports/content.
        if smoke.exists():
            shutil.rmtree(smoke)
        smoke.mkdir()
        (smoke / 'package.json').write_text('{"private":true,"type":"module"}\n')
        shutil.copyfile(KIT / 'build-support/tests/kernel.test.mjs', smoke / 'kernel.test.mjs')
        self.stage('install-release-tarballs', ['npm', 'install', '--no-audit', '--no-fund', *kernel_packages], cwd=smoke)
        self.stage('typescript-release-smoke', ['node', '--test', 'kernel.test.mjs'], cwd=smoke)
