'use strict';
(() => {
  const el = id => document.getElementById(id);
  const keyField = el('key');
  const statusField = el('connection');
  const canvas = el('overlay');
  const image = el('document-image');
  const ctx = canvas.getContext('2d');
  let key = sessionStorage.getItem('localocr_key') || '';
  let sample = null;
  let pending = [];
  let selected = -1;
  let drag = null;
  let imageURL = null;
  let toastTimer;
  keyField.value = key;

  const toast = (message, error = false) => {
    const node = el('notice'); node.textContent = message; node.className = `notice show${error ? ' error' : ''}`;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => node.className = 'notice', 4400);
  };
  async function request(path, options = {}) {
    const headers = { 'X-API-Key': key, ...(options.body ? {'Content-Type':'application/json'} : {}) };
    const res = await fetch(path, {...options, headers, cache:'no-store'});
    if (!res.ok) {
      let message = `${res.status} ${res.statusText}`;
      try { const error = await res.json(); message = typeof error.detail === 'string' ? error.detail : message; } catch (_) {}
      throw new Error(message);
    }
    const type = res.headers.get('content-type') || '';
    if (type.includes('application/json')) return res.json();
    return res.blob();
  }
  async function attempt(action) { try { await action(); } catch(e) { toast(e.message || '操作失败', true); } }

  function showButtons() {
    const ready = !!sample;
    for (const id of ['save','suggest','metadata-save','review','delete','source','split']) el(id).disabled = !ready;
    el('item-count').textContent = `${pending.length} 项`;
  }
  function draw() {
    if (!sample || !image.complete || !image.naturalWidth) return;
    const rect = image.getBoundingClientRect();
    const ratio = devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(rect.width * ratio));
    canvas.height = Math.max(1, Math.round(rect.height * ratio));
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0,0,rect.width,rect.height);
    const sx = rect.width / sample.width, sy = rect.height / sample.height;
    for (let i=0;i<pending.length;i++) {
      const b=pending[i].box;
      const xs=b.map(p=>p[0]*sx),ys=b.map(p=>p[1]*sy);
      const left=Math.min(...xs),top=Math.min(...ys),w=Math.max(...xs)-left,h=Math.max(...ys)-top;
      ctx.lineWidth = i === selected ? 2.6 : 1.7;
      ctx.strokeStyle = i === selected ? '#ef7a3c' : '#188d72';
      ctx.fillStyle = i === selected ? '#ef7a3c20' : '#188d721a';
      ctx.fillRect(left,top,w,h); ctx.strokeRect(left,top,w,h);
      ctx.font='600 11px system-ui';
      const tag = `${i+1} ${pending[i].text || '待填写'}`.slice(0,16);
      const tw=Math.min(rect.width-left,ctx.measureText(tag).width+12);
      ctx.fillStyle=i===selected?'#ef7a3c':'#188d72';
      ctx.fillRect(left,Math.max(0,top-18),tw,17);
      ctx.fillStyle='white'; ctx.fillText(tag,left+5,Math.max(12,top-5));
    }
    if(drag){ctx.setLineDash([5,4]);ctx.strokeStyle='#e7773b';ctx.lineWidth=2;ctx.strokeRect(drag.x,drag.y,drag.dx,drag.dy);ctx.setLineDash([]);}
  }
  function scaledPosition(e) {
    const r=canvas.getBoundingClientRect();
    return {x:Math.min(r.width,Math.max(0,e.clientX-r.left)),y:Math.min(r.height,Math.max(0,e.clientY-r.top)),w:r.width,h:r.height};
  }
  canvas.addEventListener('pointerdown', e => {
    if (!sample) return;
    const p=scaledPosition(e);
    drag={x:p.x,y:p.y,dx:0,dy:0,pointerId:e.pointerId};
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener('pointermove',e=>{
    if(!drag || drag.pointerId!==e.pointerId) return;
    const p=scaledPosition(e);drag.dx=p.x-drag.x;drag.dy=p.y-drag.y;draw();
  });
  canvas.addEventListener('pointerup',e=>{
    if(!drag || drag.pointerId!==e.pointerId) return;
    const p=scaledPosition(e), old=drag;drag=null;
    const x0=Math.min(old.x,p.x),x1=Math.max(old.x,p.x),y0=Math.min(old.y,p.y),y1=Math.max(old.y,p.y);
    if(x1-x0<7 || y1-y0<7){
      selected = pending.findIndex(line=>{
        const xs=line.box.map(q=>q[0]*p.w/sample.width),ys=line.box.map(q=>q[1]*p.h/sample.height);
        return p.x>=Math.min(...xs)&&p.x<=Math.max(...xs)&&p.y>=Math.min(...ys)&&p.y<=Math.max(...ys);
      });
    } else {
      const sx=sample.width/p.w, sy=sample.height/p.h;
      const l=Math.round(x0*sx),r=Math.round(x1*sx),t=Math.round(y0*sy),b=Math.round(y1*sy);
      pending.push({text:'',box:[[l,t],[r,t],[r,b],[l,b]]});selected=pending.length-1;
    }
    drawAnnotations();draw();
    const input=el(`annotation-${selected}`);
    if(input && !input.value) input.focus();
  });
  canvas.addEventListener('pointercancel',()=>{drag=null;draw()});
  new ResizeObserver(draw).observe(image);

  function drawAnnotations() {
    const box=el('annotation-list');box.replaceChildren();
    if(!pending.length){const p=document.createElement('p');p.className='empty';p.textContent='没有文字框。拖动图片创建，或使用 OCR 建议。';box.append(p);showButtons();return;}
    pending.forEach((line,i)=>{
      const card=document.createElement('div');card.className=`annotation${selected===i?' selected':''}`;
      const top=document.createElement('div');top.className='annotation-top';
      const title=document.createElement('span');title.textContent=`区域 ${String(i+1).padStart(2,'0')}`;
      const remove=document.createElement('button');remove.type='button';remove.textContent='删除';
      remove.addEventListener('click',()=>{pending.splice(i,1);selected=-1;drawAnnotations();draw()});
      top.append(title,remove);
      const input=document.createElement('input');input.id=`annotation-${i}`;input.value=line.text;input.placeholder='输入校对后的文字';input.maxLength=1024;
      input.addEventListener('focus',()=>{selected=i;draw()});
      input.addEventListener('input',()=>{pending[i].text=input.value;draw()});
      const coords=document.createElement('small');
      coords.textContent=`x ${line.box[0][0]}–${line.box[2][0]} · y ${line.box[0][1]}–${line.box[2][1]}`;
      card.append(top,input,coords);box.append(card);
    });
    showButtons();
  }
  async function refresh() {
    const [stats, list]=await Promise.all([request('/v1/datasets/stats'),request('/v1/samples?limit=100')]);
    el('s-total').textContent=stats.total;el('s-draft').textContent=stats.draft;el('s-reviewed').textContent=stats.reviewed;
    el('s-splits').textContent=`${stats.splits.train} / ${stats.splits.val} / ${stats.splits.test}`;
    const root=el('sample-list');root.replaceChildren();
    if(list.total > list.items.length) toast(`仅显示最近 ${list.items.length} 张样本，共 ${list.total} 张；更多样本可使用 API 分页访问`);
    if(!list.items.length){root.innerHTML='<p class="empty">暂无样本。导入你拥有使用权的图片开始标注。</p>';return;}
    for(const item of list.items){
      const b=document.createElement('button');b.type='button';b.className=`sample${sample&&sample.id===item.id?' active':''}`;
      const mark=document.createElement('span');mark.className='sample-mark';mark.textContent='▧';
      const info=document.createElement('span');info.className='sample-info';
      const name=document.createElement('strong');name.textContent=`${item.id.slice(0,8)} · ${item.width}×${item.height}`;
      const meta=document.createElement('small');meta.textContent=`${item.annotation_count} 个文本区域 · ${item.split}`;
      const tag=document.createElement('span');tag.className=`tag${item.status==='reviewed'?' ok':''}`;tag.textContent=item.status==='reviewed'?'已审核':'待审核';
      info.append(name,meta,tag);b.append(mark,info);b.addEventListener('click',()=>attempt(()=>openSample(item.id)));root.append(b);
    }
  }
  async function openSample(id) {
    if (sample && sample.id !== id && unsaved() && !confirm('当前标注尚未保存，确定切换图片吗？')) return;
    const item=await request(`/v1/samples/${id}`);
    const blob=await request(`/v1/samples/${id}/image`);
    if(imageURL) URL.revokeObjectURL(imageURL);
    imageURL=URL.createObjectURL(blob);
    sample=item;pending=item.annotations.map(x=>({text:x.text,box:x.box.map(p=>p.slice())}));selected=-1;
    el('source').value=item.source;el('split').value=item.split;
    el('image-title').textContent=`${item.id.slice(0,8)} · ${item.width} × ${item.height}`;
    el('image-meta').textContent=`${item.status==='reviewed'?'已审核':'待审核'} · 修订 ${item.revision} · ${item.created_at}`;
    el('canvas-help').hidden=true;el('image-stage').hidden=false;
    image.onload=()=>{draw();drawAnnotations()};image.src=imageURL;
    showButtons();await refresh();
  }
  async function connect() {
    key=keyField.value.trim();if(!key){toast('请输入 API Key',true);return;}
    await request('/v1/engines');sessionStorage.setItem('localocr_key',key);
    statusField.textContent='已连接';statusField.style.color='#2e8565';
    await refresh();toast('已连接到本地 OCR 服务');
  }
  async function importFiles(event) {
    const list=Array.from(event.target.files || []);if(!list.length)return;
    let last=null,count=0;
    for(const file of list){
      try {
        const base64=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(new Error('读取失败'));r.readAsDataURL(file)});
        const added=await request('/v1/samples',{method:'POST',body:JSON.stringify({image_base64:base64,source:file.name.slice(0,160)})});
        last=added.id;count++;
      }catch(e){toast(`${file.name}: ${e.message}`,true)}
    }
    event.target.value='';await refresh();if(last)await openSample(last);
    if(count)toast(`已导入/识别重复样本：${count} 张`);
  }
  function unsaved() {
    return sample && JSON.stringify(pending) !== JSON.stringify(sample.annotations);
  }
  function assertReady(){if(!sample)throw new Error('先选择样本')}
  async function save() {
    assertReady();if(pending.some(a=>!a.text.trim())) throw new Error('请填写每个文字框的真实文字，或删除空白框');
    if(!unsaved()) {toast('没有需要保存的改动');return;}
    sample=await request(`/v1/samples/${sample.id}/annotations`,{method:'PUT',body:JSON.stringify({expected_revision:sample.revision,lines:pending})});
    pending=sample.annotations.map(a=>({...a}));toast('标注已保存；如需用于训练，请再次人工审核');await openSample(sample.id);
  }
  async function metadata(status=null) {
    assertReady();if(unsaved())throw new Error('存在未保存的标注，请先保存后再修改属性或标记审核');const next=await request(`/v1/samples/${sample.id}`,{method:'PATCH',body:JSON.stringify({expected_revision:sample.revision,source:el('source').value,split:el('split').value,...(status?{status}:{})})});
    sample=next;toast(status==='reviewed'?'已审核，可进入数据集导出':'样本属性已保存');await openSample(sample.id);
  }
  async function suggest(){
    assertReady();if(pending.length && !confirm('使用 OCR 建议替换当前未保存的标注？'))return;
    const result=await request(`/v1/samples/${sample.id}/suggest`,{method:'POST'});
    pending=(result.lines||[]).filter(x=>x.text&&x.box&&x.box.length===4).map(x=>({text:x.text,box:x.box}));selected=-1;
    drawAnnotations();draw();toast(`识别到 ${pending.length} 个文本区域，请人工核对后保存`);
  }
  async function remove(){
    assertReady();if(!confirm('确认永久删除这个样本和对应标注？'))return;
    await request(`/v1/samples/${sample.id}?expected_revision=${sample.revision}`,{method:'DELETE'});
    sample=null;pending=[];selected=-1;image.src='';if(imageURL)URL.revokeObjectURL(imageURL);imageURL=null;
    el('image-stage').hidden=true;el('canvas-help').hidden=false;el('image-title').textContent='选择图片开始标注';drawAnnotations();showButtons();await refresh();toast('样本已删除');
  }
  async function exportZip(){
    const zip=await request('/v1/datasets/export?reviewed_only=true');
    const url=URL.createObjectURL(zip);const a=document.createElement('a');a.href=url;a.download='localocr-reviewed-dataset.zip';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);toast('已导出人工审核样本');
  }
  el('connect').addEventListener('click',()=>attempt(connect));
  keyField.addEventListener('keydown',e=>{if(e.key==='Enter')attempt(connect)});
  el('files').addEventListener('change',e=>attempt(()=>importFiles(e)));
  el('refresh').addEventListener('click',()=>attempt(refresh));
  el('save').addEventListener('click',()=>attempt(save));
  el('metadata-save').addEventListener('click',()=>attempt(()=>metadata()));
  el('review').addEventListener('click',()=>attempt(()=>metadata('reviewed')));
  el('suggest').addEventListener('click',()=>attempt(suggest));
  el('delete').addEventListener('click',()=>attempt(remove));
  el('export').addEventListener('click',()=>attempt(exportZip));
  showButtons();if(key)attempt(connect);
})();
