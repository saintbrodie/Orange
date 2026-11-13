const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// A small DOM fixture exercises the real editor's load/save and user actions.
class Element {
  set value(value) { this._value = String(value); }
  get value() { return this._value; }
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.events = {}; this.value = ''; this.id = ''; }
  append(...nodes) { for (const node of nodes) { node.remove(); node.parentElement = this; this.children.push(node); } }
  get childElementCount() { return this.children.length; }
  querySelector(selector) { if (selector === 'h4') return this.children.find(n=>n.tagName==='h4'); return this.querySelectorAll(selector)[0]; }
  insertBefore(node, before) { node.remove(); const index=this.children.indexOf(before); this.children.splice(index<0?this.children.length:index,0,node); node.parentElement=this; }
  replaceWith(node) { const parent=this.parentElement; const index=parent.children.indexOf(this); node.remove(); parent.children[index]=node;node.parentElement=parent;this.parentElement=null; }
  remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(n => n !== this); this.parentElement = null; }
  replaceChildren(...nodes) { for (const child of [...this.children]) child.remove(); this.append(...nodes); }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, action) { this.events[name] = action; }
  insertAdjacentElement(_, node) { this.parentElement.append(node); }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [
      ...(['input', 'button'].includes(selector) && child.tagName === selector || selector === '[data-ratio-row]' && child.dataset.ratioRow ? [child] : []),
      ...child.querySelectorAll(selector),
    ]);
  }
}
const root = new Element('main');
global.document = {
  createElement: tag => new Element(tag),
  getElementById: id => {
    const find = node => node.id === id ? node : node.children.map(find).find(Boolean);
    return find(root);
  },
  querySelectorAll: selector => root.querySelectorAll(selector),
};
global.window = {};
global.adminFetch = async () => ({ok:false});
Element.prototype.dispatchEvent = function () {};
global.renderMappings = (mapping, context = 'base') => {
  const prefix=context==='alternate'?'alt-':'';
  const root = document.getElementById(context==='alternate'?'alternate-node-mappings':'node-mappings-container'); root.replaceChildren();
  for (const key of ['prompt','image','image2','seed','duration','outputText','resolution']) {
    const slot = key === 'resolution' ? mapping.width || mapping.height : mapping[key];
    if (!slot) continue;
    const card = new Element('div'); card.id = `${prefix}map-${key}-container`;root.append(card);
    for (const [suffix, val] of [['enable',''],['node',slot.nodeId || ''],['field',slot.field || '']]) {
      const control=new Element('input');control.id=`${prefix}map-${key}-${suffix}`;control.value=val;control.checked=true;card.append(control);
    }
    if (key === 'resolution') for (const [name, field] of [['wfield',mapping.width?.field],['hfield',mapping.height?.field]]) {const input=new Element('input');input.id=prefix+'map-res-'+name;input.value=field;card.append(input);}
    if (key === 'seed') {const input=new Element('input');input.id=prefix+'map-seed-rand';input.checked=slot.generateRandom;card.append(input);}
  }
};
const section = new Element('section'); root.append(section);
const mappings = new Element('div'); mappings.id = 'node-mappings-container'; section.append(mappings);
const file = new Element('input'); file.id = 'edit-tool-file'; root.append(file);
vm.runInThisContext(fs.readFileSync(path.join(__dirname, '../static/tool-input-editor.js'), 'utf8'));
const editor = window.ToolInputEditor;
const manifests = fs.readdirSync(path.join(__dirname, '../workflow-packs')).map(name =>
  JSON.parse(fs.readFileSync(path.join(__dirname, '../workflow-packs', name, 'manifest.json'), 'utf8')));
for (const manifest of manifests) {
  const original = manifest.tool;
  file.value = original.workflowFile;
  editor.load(original, [original.workflowFile], {});
  const result = editor.apply(structuredClone(original));
  assert.deepEqual(result, original, `${manifest.id} must survive an editor round trip unchanged`);
}
// Create a custom tool using the same visible controls; no curated IDs involved.
const custom = {id: 'custom-editor', name: 'Custom', workflowFile: 'base.json', nodeMapping: {image: {nodeId: '1', field: 'image'}}};
file.value = custom.workflowFile;
editor.load(custom, ['base.json', 'reference.json'], {});
document.getElementById('tool-input-mode').value = 'referenceVariant';
document.getElementById('tool-input-mode').events.change();
document.getElementById('tool-alternate-file').value = 'reference.json';
document.getElementById('map-image-node').value = '9';
for (const [key, id] of [['image', '20'], ['image2', '21']]) {
  document.getElementById(`alt-map-${key}-node`).value = id;
  document.getElementById(`alt-map-${key}-field`).value = 'image';
}
const result = editor.apply(structuredClone(custom));
assert.equal(result.referenceVariant.nodeMapping.image2.nodeId, '21');
assert.equal(result.nodeMapping.image.nodeId, '9', 'Switching modes must preserve unsaved base edits');
assert.equal(result.referenceVariant.workflowFile, 'reference.json');
document.getElementById('tool-alternate-file').value = '';
assert.throws(() => editor.apply(structuredClone(custom)), /file and an Image mapping/);
console.log(`Passed: lossless editor round trips for ${manifests.length} curated tools, custom optional reference creation, and incomplete mode rejection.`);

(async () => {
  global.adminFetch = async () => ({ok:true,json:async()=>({'1':{class_type:'LoadImage',inputs:{image:'example.png'}}})});
  file.value = custom.workflowFile;
  editor.load(custom, ['base.json'], {});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(document.getElementById('map-image-node').tagName, 'select');
  assert.equal(document.getElementById('map-image-field').tagName, 'select');
  console.log('Passed: workflow-backed node and field dropdowns.');
})().catch(error => {console.error(error);process.exitCode=1;});
