#!/usr/bin/env python3
"""Build and exercise a12-kernel-demo against a verified public bootstrap release."""
import argparse
import os
from pathlib import Path

from bootstrap import KIT, BootstrapError, jdk, load_release, node24
from build_release import ReleaseBuilder, require_verified_release, verify_no_dependency_model_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('demo', type=Path)
    parser.add_argument('--home', type=Path, default=Path(os.environ.get(
        'A12_BOOTSTRAP_HOME', KIT.parent / '.a12-bootstrap' / '2026.06-ext2')))
    args = parser.parse_args()
    state, demo = args.home.resolve(), args.demo.resolve()
    release = load_release()
    require_verified_release(state, release)
    env = os.environ.copy()
    env['JAVA_HOME'] = jdk(21)
    env['GRADLE_USER_HOME'] = str(Path(env.get('A12_GRADLE_USER_HOME', state / 'gradle-home')).resolve())
    env['A12_BOOTSTRAP_HOME'] = str(state)
    env['npm_config_userconfig'] = os.devnull
    env['npm_config_registry'] = 'https://registry.npmjs.org/'
    env['pnpm_config_store_dir'] = str(state / 'pnpm-store')
    env['npm_config_manage_package_manager_versions'] = 'false'
    env['PATH'] = os.pathsep.join([str(Path(env['JAVA_HOME']) / 'bin'),
        str(state / f"tools/pnpm-{release['pnpm_version']}/node_modules/.bin"), env.get('PATH', '')])
    node24(env)
    gradle = [env.get('GRADLE_BIN', str(state / f"tools/gradle-{release['gradle_version']}/bin/gradle")),
              '--console=plain', '--no-configuration-cache', '--max-workers=2', '-p', demo]
    builder = ReleaseBuilder(state, release, gradle, env)
    classpath = state / 'logs/consumer-classpath.txt'
    builder.env['A12_CONSUMER_CLASSPATH'] = str(classpath)
    builder.stage('consumer-classpath', gradle + ['-I', KIT / 'build-support/consumer-classpath.init.gradle',
                                                 'bootstrapConsumerClasspath'])
    verify_no_dependency_model_files(Path(line) for line in classpath.read_text().splitlines())
    builder.stage('consumer-build', gradle + ['clean', 'build', 'demo', 'showcases', 'runTyped', 'runTs'])
    print('Consumer build, Java showcases, typed accessors and TypeScript parity passed.')


if __name__ == '__main__':
    try:
        main()
    except BootstrapError as error:
        raise SystemExit(str(error))
