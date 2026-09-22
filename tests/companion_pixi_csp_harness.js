// 실제 번들이 문자열 코드 생성 금지 환경에서 초기화되는지 검사한다.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.resolve(__dirname, '../assets/web');
const context = vm.createContext({ console }, {
    codeGeneration: { strings: false, wasm: true }
});
vm.runInContext(fs.readFileSync(path.join(web, 'lib/pixi.min.js'), 'utf8'), context);
assert.throws(() => vm.runInContext('new Function("return 1")', context));
const shim = path.join(web, 'lib/pixi-unsafe-eval.min.js');
if (fs.existsSync(shim)) vm.runInContext(fs.readFileSync(shim, 'utf8'), context);
vm.runInContext('PIXI.ShaderSystem.prototype.systemCheck.call({})', context);
assert.throws(() => vm.runInContext('new Function("return 1")', context));
