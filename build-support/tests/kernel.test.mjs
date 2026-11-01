import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';

const require = createRequire(new URL('./package.json', import.meta.url));
const load = async (name) => import(pathToFileURL(require.resolve(name)).href);
const runtime = await load('@com.mgmtp.a12.kernel/kernel-core-runtime-ts');
const api = await load('@com.mgmtp.a12.kernel/kernel-core-runtime-api-ts');
const facade = await load('@com.mgmtp.a12.kernel/kernel-md-facade');
const custom = await load('@com.mgmtp.a12.kernel/kernel-core-customfieldtype-impl');

test('runtime date comparison handles equality, ordering and missing values', () => {
  const { BedingungsOperatorHelper: compare, VglOp } = runtime;
  const earlier = new Date('2026-01-01T00:00:00Z');
  const later = new Date('2026-02-01T00:00:00Z');
  assert.equal(compare.vergleicheDATUM(VglOp.LT, earlier, later), true);
  assert.equal(compare.vergleicheDATUM(VglOp.GT, earlier, later), false);
  assert.equal(compare.vergleicheDATUM(VglOp.EQ, earlier, new Date(earlier)), true);
  assert.equal(compare.vergleicheDATUM(VglOp.EQ, undefined, undefined), false);
});

test('runtime API loads localized validation messages', () => {
  const messages = api.defaultResourceProvider;
  assert.equal(messages.gettext('no-such-bootstrap-key', 'en'), undefined);
  assert.equal(messages.gettext('ZAHL_MIT_UNGUELTIGEN_ZEICHEN', 'en'), 'Only numbers are allowed.');
  assert.notEqual(messages.gettext('ZAHL_MIT_UNGUELTIGEN_ZEICHEN', 'de'),
    messages.gettext('ZAHL_MIT_UNGUELTIGEN_ZEICHEN', 'en'));
});

test('custom field validation accepts a valid IBAN and rejects a changed checksum', () => {
  const verifier = custom.IBANVerifier.getInstance();
  assert.equal(verifier.validate('DE89370400440532013000', {}, false), undefined);
  assert.ok(verifier.validate('DE88370400440532013000', {}, false));
  assert.ok(verifier.validate('invalid', {}, false));
});

test('facade deserializes an exported metamodel and resolves its root group', async () => {
  const source = await readFile(join(process.env.A12_MM_DIR,
    'documentModels/CT_FIELD_TYPE_ATTRIBUTES_1/a12types-ct_field_type_attributes-1-3.1.json'), 'utf8');
  const raw = JSON.parse(source);
  const factory = new facade.DocumentServiceFactory();
  const model = factory.getDocumentModelSerializer().deserialize(source);
  assert.equal(model.header.id, raw.header.id);
  const group = raw.content.modelRoot.rootGroups[0];
  const search = factory.getDocumentModelSearchService(model);
  const path = search.getPathById(group.id);
  assert.ok(path);
  assert.equal(search.getByPath(path).name, group.name);
  assert.throws(() => factory.getDocumentModelSerializer().deserialize('{broken'));
});

test('generated browser lexer recognizes arithmetic and reports invalid input', async () => {
  const entry = require.resolve('@com.mgmtp.a12.kernel/kernel-core-parser-web');
  const { createLexer } = await import(pathToFileURL(join(dirname(entry), 'internal/ParserService.js')).href);
  const parserRequire = createRequire(entry);
  const antlrModule = await import(pathToFileURL(parserRequire.resolve('antlr4ForA12Kernel')).href);
  const antlr = antlrModule.default;
  const Lexer = createLexer('en');
  const tokenize = (input) => {
    const lexer = new Lexer(antlr.CharStreams.fromString(input));
    const errors = [];
    lexer.removeErrorListeners();
    lexer.addErrorListener({ syntaxError: (...args) => errors.push(args) });
    const tokens = new antlr.CommonTokenStream(lexer);
    tokens.fill();
    return { errors, tokens: tokens.tokens.filter(t => t.type !== -1 && t.channel === 0).map(t => t.text) };
  };
  assert.deepEqual(tokenize('1 + 2').tokens, ['1', '+', '2']);
  assert.deepEqual(tokenize('1 + 2').errors, []);
  assert.ok(tokenize('☃').errors.length > 0);
});
