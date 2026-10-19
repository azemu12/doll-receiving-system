/**
 * 第5阶段：前端摄像头逻辑的「无摄像头」自动化测试。
 *
 * 为什么要这个脚本：
 * - pytest 只能验证后端 API 和页面源码，无法真正执行浏览器里的 JS；
 * - 这里用 Node + 极简 DOM 桩，把 app/templates/vision.html 里的 script
 *   原样抽出来执行，并注入一个假的 getUserMedia / canvas / fetch，
 *   从而在【电脑不需要连接摄像头】的前提下验证整条拍照识别链路。
 *
 * 运行：node tools/check_camera_js.js   （需 Node >= 16，可选执行）
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const HTML_PATH = path.join(__dirname, '..', 'app', 'templates', 'vision.html');

function extractScript(html) {
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  if (!m) throw new Error('vision.html 中未找到 <script> 块');
  // 渲染 Jinja 模板变量（页面真实渲染时由 FastAPI 传入配置值）
  return m[1].replace(/\{\{\s*max_image_mb\s*\}\}/g, '10');
}

function makeCtx() {
  const els = {};
  const calls = [];
  let drawn = null;

  function makeEl(id) {
    const el = {
      id, children: [], style: {}, disabled: false, innerHTML: '', textContent: '',
      srcObject: null, href: '', files: null, videoWidth: 1280, videoHeight: 720,
      _cls: new Set(),
      classList: {
        add: (c) => el._cls.add(c),
        remove: (c) => el._cls.delete(c),
        contains: (c) => el._cls.has(c),
      },
      appendChild: (c) => el.children.push(c),
      removeAttribute: () => {},
      setAttribute: () => {},
      addEventListener: () => {},
      scrollIntoView: () => {},
      async play() {},
      getContext: () => ({ drawImage: (a) => { drawn = a; } }),
      // 假 Clement：模拟 canvas.toBlob 产出一张 45KB 的 JPEG
      toBlob: (cb, type) => cb({ size: 45678, type }),
    };
    Object.defineProperty(el, 'className', {
      get: () => Array.from(el._cls).join(' '),
      set: (v) => { el._cls = new Set(String(v).split(/\s+/).filter(Boolean)); },
    });
    return el;
  }
  const el = (id) => (els[id] || (els[id] = makeEl(id)));

  class FormDataStub {
    constructor() { this.items = []; }
    append(k, v, fn) { this.items.push({ k, v, fn }); }
  }

  const sandbox = {
    console, setTimeout, Promise, Math, String, Number, Object, Array, JSON, RegExp, Date, Error, isNaN,
    FormData: FormDataStub,
    URL: { createObjectURL: () => 'blob:fake' },
    document: {
      getElementById: el,
      querySelectorAll: () => [],
      createElement: (tag) => makeEl(tag),
    },
    fetch: async (url, opts) => {
      calls.push({ url, opts });
      if (url === '/vision/match') {
        return {
          ok: true, status: 200,
          json: async () => ({
            candidates: [
              {
                product_id: 11, sku: 'S001', name: '星黛露', size: '20cm', style: '普通款',
                sale_price: 40, similarity: 0.9132, reference_image: '/uploads/a.jpg',
                has_embedding: true, image_count: 3,
              },
              {
                product_id: 12, sku: 'S002', name: '星黛露', size: '20cm', style: '特别款',
                sale_price: 50, similarity: null, reference_image: '',
                has_embedding: false, image_count: 0,
              },
            ],
          }),
        };
      }
      return { ok: true, status: 200, json: async () => ({ candidates: [] }) };
    },
  };
  sandbox.window = { isSecureContext: true, addEventListener: () => {} };
  sandbox.navigator = { mediaDevices: { getUserMedia: null } };
  sandbox.globalThis = sandbox;

  return { sandbox, el, calls, getDrawn: () => drawn };
}

function run(code, ctx) {
  vm.createContext(ctx.sandbox);
  vm.runInContext(code, ctx.sandbox);
  return ctx;
}

let failed = 0;
function assert(cond, msg) {
  if (cond) console.log('  ✅ ' + msg);
  else { console.error('  ❌ ' + msg); failed++; }
}

(async () => {
  const code = extractScript(fs.readFileSync(HTML_PATH, 'utf8'));
  const okStream = async () => ({ getTracks: () => [{ stop: () => {} }] });

  // ---------- 用例1：正常启动 -> 拍照 -> 走 /vision/match ----------
  console.log('用例1：启动摄像头 → 拍照识别');
  const c1 = run(code, makeCtx());
  c1.sandbox.navigator.mediaDevices.getUserMedia = okStream;
  await c1.sandbox.startCamera();
  assert(/已就绪/.test(c1.el('cam-status').textContent), '摄像头状态：已就绪');
  assert(c1.el('capture-btn').disabled === false, '拍照按钮变为可用');
  assert(c1.el('camera-placeholder').style.display === 'none', '启动后隐藏占位提示');

  await c1.sandbox.captureAndMatch();
  const m = c1.calls.find((x) => x.url === '/vision/match');
  const f = m && m.opts.body.items[0];
  assert(!!m && m.opts.method === 'POST', '拍照后 POST 到 /vision/match');
  assert(f && f.k === 'file' && f.fn === 'camera.jpg' && f.v.type === 'image/jpeg',
    '以 camera.jpg / image/jpeg 提交');
  assert(!!c1.getDrawn(), 'canvas 已抓帧');
  assert(c1.el('preview-box').style.display === 'block', '右侧显示最近拍摄照片');

  const list = c1.el('cand-list').children;
  assert(list.length === 3, '渲染 2 个候选 + 1 个「其他」');
  assert(/相似度 91\.3%/.test(list[0].innerHTML), '有 embedding 的显示相似度');
  assert(/未建立图库/.test(list[1].innerHTML), '无 embedding 的显示未建立图库');
  assert(/其他/.test(list[2].innerHTML), '始终存在「其他」');
  assert(c1.el('final-panel').style.display === 'none', '未选择时收货面板隐藏');
  c1.sandbox.confirmChoice();
  assert(c1.el('final-panel').style.display === 'none', '未选择时 confirmChoice 不生效');

  c1.sandbox.chooseSku(0);
  assert(c1.el('select-panel').style.display === 'block', '选择后显示已选款式');
  c1.sandbox.confirmChoice();
  assert(c1.el('receive-link').href === '/receive?product_id=11', '收货跳转链接正确');
  assert(c1.calls.every((x) => x.url !== '/inventory'), '全流程未调用 /inventory');

  c1.sandbox.retake();
  assert(c1.el('preview-box').style.display === 'none', '重新拍照清空截图');
  assert(c1.el('final-panel').style.display === 'none', '重新拍照清空确认面板');

  // ---------- 用例2-5：摄像头各种异常 ----------
  const cases = [
    ['NotAllowedError', '摄像头权限被拒绝'],
    ['NotFoundError', '未检测到摄像头设备'],
    ['NotReadableError', '被其他程序占用'],
    ['OverconstrainedError', '不支持请求的分辨率'],
    ['SecurityError', '安全策略阻止'],
  ];
  for (const [errName, expect] of cases) {
    const c = run(code, makeCtx());
    const e = new Error('mock'); e.name = errName;
    c.sandbox.navigator.mediaDevices.getUserMedia = async () => { throw e; };
    await c.sandbox.startCamera();
    assert(new RegExp(expect).test(c.el('cam-status').textContent), `异常 ${errName} → 提示「${expect}」`);
    assert(c.el('capture-btn').disabled === true, `异常 ${errName} 后拍照按钮保持禁用`);
  }

  console.log('用例6：运行环境不支持');
  const c4 = run(code, makeCtx());
  c4.sandbox.navigator.mediaDevices = undefined;
  await c4.sandbox.startCamera();
  assert(/不支持摄像头接口/.test(c4.el('cam-status').textContent), '提示：浏览器不支持摄像头接口');

  const c5 = run(code, makeCtx());
  c5.sandbox.window.isSecureContext = false;
  c5.sandbox.navigator.mediaDevices.getUserMedia = okStream;
  await c5.sandbox.startCamera();
  assert(/非安全上下文/.test(c5.el('cam-status').textContent), '提示：非安全上下文需用 localhost 访问');

  // ---------- 用例7：图库未建库时兜底 ----------
  console.log('用例7：AI 图库未建库 → 兜底列出全部 SKU');
  const c6 = run(code, makeCtx());
  c6.sandbox.navigator.mediaDevices.getUserMedia = okStream;
  c6.sandbox.fetch = async (url, opts) => {
    c6.calls.push({ url, opts });
    if (url === '/vision/match') {
      return {
        ok: false, status: 400,
        json: async () => ({ detail: '商品图库尚未建立Embedding，请先运行：python -m app.vision.build_embeddings' }),
      };
    }
    return {
      ok: true, status: 200,
      json: async () => ({
        candidates: [{
          product_id: 2, sku: 'S001', name: '星黛露', size: '20cm', style: '普通款',
          sale_price: 40, similarity: null, reference_image: '', has_embedding: false, image_count: 0,
        }],
      }),
    };
  };
  await c6.sandbox.startCamera();
  await c6.sandbox.captureAndMatch();
  assert(c6.calls.some((x) => x.url === '/vision/skus'), '兜底调用 /vision/skus');
  assert(/AI 图库尚未建立 Embedding/.test(c6.el('msg').textContent), '给出建库提示');
  assert(c6.el('cand-list').children.length === 2, '兜底后仍可人工选择');

  console.log(failed === 0 ? '\n全部通过 ✅' : `\n${failed} 项失败 ❌`);
  process.exit(failed === 0 ? 0 : 1);
})();
