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
  async function exportPaddle() {
    const zip = await request('/v1/datasets/export/paddle-det');
    const url = URL.createObjectURL(zip);
    const a = document.createElement('a');
    a.href = url; a.download = 'localocr-paddle-det.zip';
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
    toast('已导出检测标注；尚未执行模型训练');
  }
  el('export').addEventListener('click',()=>attempt(exportZip));
  el('export-paddle').addEventListener('click',()=>attempt(exportPaddle));
  async function exportRecognition() {
    const zip = await request('/v1/datasets/export/paddle-rec');
    const url = URL.createObjectURL(zip);
    const a = document.createElement('a');
    a.href = url; a.download = 'localocr-paddle-rec.zip';
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
    toast('已导出人工审核的识别训练集，请先解压并检查训练/验证分组');
  }
  function trainingConfig() {
    return {
      paddle_repo: el('train-repo').value.trim(),
      dataset_dir: el('train-data').value.trim(),
      pretrained_model: el('train-weight').value.trim(),
      epochs: Number(el('train-epochs').value),
      batch_size: Number(el('train-batch').value),
      use_gpu: el('train-gpu').value === 'true',
      ...(el('train-resume-id').value.trim()
        ? {resume_run_id: el('train-resume-id').value.trim(),
           resume_checkpoint: el('train-resume-checkpoint').value} : {})
    };
  }
  async function trainingPlan() {
    const plan = await request('/v1/training/plan',
      {method:'POST', body:JSON.stringify(trainingConfig())});
    el('train-output').textContent =
      '配置校验通过。训练数 ' + plan.train_count + ' · 验证数 ' +
      plan.val_count + ' · 保留测试数 ' + plan.test_count +
      '\n模型输出: ' + plan.output_dir +
      (plan.resume_from ? '\n恢复自: ' + plan.resume_from.run_id + ' / ' + plan.resume_from.checkpoint : '') +
      '\n请确认数据和预训练权重来源后再点击启动。';
  }
  async function trainingStart() {
    if (!confirm('将使用本机计算资源运行 PaddleOCR 模型微调。确定启动吗？')) return;
    const status = await request('/v1/training/start',
      {method:'POST', body:JSON.stringify(trainingConfig())});
    displayTrainingStatus(status);
    toast('训练任务已启动，请通过状态与日志确认真实训练是否成功');
  }
  function displayTrainingStatus(status) {
    el('train-output').textContent =
      '任务状态：' + status.status +
      (status.id ? '\n任务：' + status.id : '') +
      (status.output_dir ? '\n模型目录：' + status.output_dir : '') +
      (status.exit_code !== null && status.exit_code !== undefined
        ? '\n退出码：' + status.exit_code : '') +
      (status.model_files && status.model_files.length
        ? '\n模型文件：' + status.model_files.join(', ') : '') +
      (status.log_tail ? '\n\n最后日志：\n' + status.log_tail : '');
  }
  async function trainingStatus() {
    displayTrainingStatus(await request('/v1/training/status'));
  }
  async function trainingCancel() {
    if (!confirm('确定停止当前本地模型训练任务吗？')) return;
    displayTrainingStatus(await request('/v1/training/cancel', {method:'POST'}));
  }
  el('export-rec').addEventListener('click',()=>attempt(exportRecognition));
  el('train-plan').addEventListener('click',()=>attempt(trainingPlan));
  el('train-start').addEventListener('click',()=>attempt(trainingStart));
  el('train-status').addEventListener('click',()=>attempt(trainingStatus));
  el('train-cancel').addEventListener('click',()=>attempt(trainingCancel));

  function showAux(value) { el('aux-output').textContent = JSON.stringify(value, null, 2); }
  el('train-history').addEventListener('click', () => attempt(async () => {
    showAux(await request('/v1/training/history'));
  }));
  async function showRegisteredModels() {
    const records = (await request('/v1/models')).items || [];
    const lines = ['本地训练检查点 · 状态清单（不是已经部署的 OCR 模型）'];
    if (!records.length) lines.push('暂无已登记版本。');
    for (const [index, entry] of records.entries()) {
      lines.push((index + 1) + '. ' + entry.filename + ' · ' + entry.id +
        '\n   训练任务：' + entry.run_id +
        '\n   文件 SHA-256：' + entry.sha256 +
        '\n   验收状态：' + entry.state +
        '\n   可切换到正在使用的 OCR 引擎：否（尚未导出/验证兼容推理格式）');
    }
    el('model-output').textContent = lines.join('\n');
  }
  el('model-list').addEventListener('click', () => attempt(showRegisteredModels));
  el('model-register').addEventListener('click', () => attempt(async () => {
    if (!confirm('只登记本地模型文件及其哈希；不会切换正在使用的 OCR 模型。继续？')) return;
    await request('/v1/models/register', {
      method: 'POST', body: JSON.stringify({
        run_id: el('model-run').value.trim(),
        filename: el('model-file').value.trim()
      })
    });
    await showRegisteredModels();
    toast('检查点已登记，但尚未完成推理兼容性验收，因此不会自动启用');
  }));
  const qualityMath = globalThis.LocalOCRQualityReport;
  if (!qualityMath) throw new Error('本地评估组件未加载，请检查工作台文件完整性');
  let allEvaluationRunning = false;
  let manualEvaluationRunning = false;
  let stopAllEvaluation = false;
  let lastQualityReport = null;
  const MAX_BATCH_EVALUATION_IMAGES = 150;
  const exportQualityButton = el('eval-local-export');
  function clearQualityReport() {
    lastQualityReport = null;
    exportQualityButton.disabled = true;
  }
  function qualityText(report) {
    const e = report.evaluation, m = report.metrics;
    const pct = value => value === null ? '—' : (value * 100).toFixed(2) + '%';
    const lines = [
      '本地 OCR 测试集汇总 · ' + (e.complete ? '已完成' : '部分结果（' + e.status + '）'),
      '已评估：' + e.evaluated_samples + '/' + (e.total_test_samples ?? '?') +
        ' 张图片；' + e.evaluated_regions + ' 个文字区域',
      '引擎：' + report.actual_engines.join(', '),
      '区域完全匹配：' + m.exact_matches + '/' + e.evaluated_regions +
        '（' + pct(m.exact_match_rate) + '）',
      '字符错误率 CER：' + pct(m.cer) +
        '（' + m.edit_errors + ' 编辑错误 / ' + m.reference_characters + ' 参考字符）',
      '未识别出文字的区域：' + m.empty_predictions,
      '单区域平均推理耗时：' + (m.inference_ms_mean ?? '—') + ' ms',
      '按参考文字长度分析：'
    ];
    for (const name of qualityMath.LENGTH_BUCKETS) {
      const g = m.by_reference_length[name];
      lines.push('  ' + name + ' 字符：' + g.regions + ' 区域，完全匹配 ' +
        pct(g.exact_match_rate) + '，CER ' + pct(g.cer));
    }
    if (!e.complete) lines.push('注意：尚未覆盖整个测试集，不能将本报告当作全量准确率。');
    lines.push('测试集修订指纹：' + (e.dataset_fingerprint || '无'));
    lines.push('最多 10 项错误区域索引（不包含原始文字）：');
    lines.push(JSON.stringify(report.error_examples, null, 2));
    return lines.join('\n');
  }
  function saveQualityReport() {
    if (!lastQualityReport || allEvaluationRunning || manualEvaluationRunning) {
      toast('请先完成或停止批量评测后再导出', true);
      return;
    }
    const payload = JSON.stringify(lastQualityReport, null, 2) + '\n';
    const blob = new Blob([payload], {type: 'application/json;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    try {
      const link = document.createElement('a');
      link.href = url;
      link.download = 'localocr-ocr-quality-' +
        new Date().toISOString().slice(0, 10) + '.json';
      document.body.append(link);
      link.click();
      link.remove();
    } finally {
      setTimeout(() => URL.revokeObjectURL(url), 1500);
    }
    toast('已导出本地 OCR 指标 JSON，不包含图片及原始识别文本');
  }
  exportQualityButton.addEventListener('click', saveQualityReport);
  async function runAggregateEvaluation() {
    if (allEvaluationRunning || manualEvaluationRunning) return;
    allEvaluationRunning = true;
    stopAllEvaluation = false;
    clearQualityReport();
    const select = el('eval-local-engine');
    const first = el('eval-local-run');
    const next = el('eval-local-next');
    const all = el('eval-local-all');
    const stop = el('eval-local-stop');
    const engineName = select.value;
    const previousNextDisabled = next.disabled;
    select.disabled = true;
    first.disabled = true;
    next.disabled = true;
    all.disabled = true;
    stop.disabled = false;
    const aggregate = qualityMath.createAccumulator();
    let status = 'failed';
    try {
      while (!stopAllEvaluation && aggregate.samples < MAX_BATCH_EVALUATION_IMAGES) {
        const offset = aggregate.nextOffset;
        let limit = Math.min(5, MAX_BATCH_EVALUATION_IMAGES - aggregate.samples);
        let page = null;
        while (!stopAllEvaluation) {
          try {
            page = await request('/v1/evaluation/reviewed-test', {
              method: 'POST', body: JSON.stringify({engine: engineName, limit, offset})
            });
            break;
          } catch (error) {
            // Use a single image when the selected page has >40 regions.
            // An individual image with >40 regions remains a hard error.
            if (limit > 1 && String(error.message).includes('1..40 annotated regions')) {
              limit = 1;
            } else {
              throw error;
            }
          }
        }
        if (!page) break;
        qualityMath.includePage(aggregate, page);
        const complete = aggregate.samples === aggregate.available;
        el('aux-output').textContent = qualityText(
          qualityMath.finalize(aggregate, {engine: engineName, reason: complete ? 'complete' : 'in_progress'}));
        if (complete) {
          status = 'complete';
          break;
        }
      }
      if (status !== 'complete') {
        status = stopAllEvaluation ? 'cancelled' : 'limit_reached';
      }
      if (aggregate.samples) {
        lastQualityReport = qualityMath.finalize(aggregate, {engine: engineName, reason: status});
        exportQualityButton.disabled = false;
        el('aux-output').textContent = qualityText(lastQualityReport);
      }
      toast(status === 'complete' ? '整个测试集的评测结果已汇总，可导出 JSON'
        : '评测已停止或达到上限；结果标记为部分报告');
    } catch (error) {
      if (aggregate.samples) {
        const reason = String(error.message).includes('dataset changed') ||
          String(error.message).includes('数据集') ? 'invalidated' : 'failed';
        lastQualityReport = qualityMath.finalize(aggregate, {engine: engineName, reason});
        exportQualityButton.disabled = false;
        el('aux-output').textContent = qualityText(lastQualityReport);
      }
      throw error;
    } finally {
      allEvaluationRunning = false;
      stop.disabled = true;
      select.disabled = false;
      first.disabled = false;
      next.disabled = previousNextDisabled;
      all.disabled = false;
    }
  }
  el('eval-local-all').addEventListener('click', () => attempt(runAggregateEvaluation));
  el('eval-local-stop').addEventListener('click', () => {
    stopAllEvaluation = true;
    el('eval-local-stop').disabled = true;
    toast('已请求停止；当前批次完成后将生成部分报告');
  });

  let evaluatedNextOffset = 0;
  async function runLocalBenchmark(nextPage = false) {
    if (allEvaluationRunning || manualEvaluationRunning) return;
    manualEvaluationRunning = true;
    clearQualityReport();
    const offset = nextPage ? evaluatedNextOffset : 0;
    const select = el('eval-local-engine');
    const runButton = el('eval-local-run');
    const nextButton = el('eval-local-next');
    const allButton = el('eval-local-all');
    runButton.disabled = true;
    nextButton.disabled = true;
    allButton.disabled = true;
    select.disabled = true;
    try {
      const report = await request('/v1/evaluation/reviewed-test', {
        method: 'POST',
        body: JSON.stringify({engine: select.value, limit: 5, offset})
      });
      evaluatedNextOffset = report.next_offset;
      el('aux-output').textContent =
        '本地识别准确率 · 已人工审核的独立测试集（仅本批）\n' +
        '引擎：' + report.actual_engines.join(', ') +
        ' | 测试图片：' + report.evaluated_samples +
        ' | 文本区域：' + report.evaluated_regions +
        '\n区域完全正确：' + report.exact_matches + '/' + report.evaluated_regions +
        '（' + (report.exact_match_rate * 100).toFixed(2) + '%）' +
        '\n字符错误率 CER：' + (report.cer * 100).toFixed(2) + '%' +
        ' | 单区域平均耗时：' + report.inference_ms_mean + ' ms' +
        '\n已评估图片偏移：' + offset + ' → ' + report.next_offset +
        ' / ' + report.available_test_samples +
        (report.has_more ? '\n还有下一批；各批次结果不能直接当整体准确率。' : '\n当前没有后续批次。') +
        '\n错误示例（不返回原始标注文本）：\n' +
        JSON.stringify(report.error_examples, null, 2);
      nextButton.disabled = !report.has_more;
      toast('本地 OCR 测试完成，结果未写入标注库');
    } finally {
      manualEvaluationRunning = false;
      runButton.disabled = false;
      allButton.disabled = false;
      select.disabled = false;
    }
  }
  el('eval-local-engine').addEventListener('change', () => {
    evaluatedNextOffset = 0;
    el('eval-local-next').disabled = true;
    clearQualityReport();
  });
  el('eval-local-run').addEventListener('click', () => attempt(() => runLocalBenchmark()));
  el('eval-local-next').addEventListener('click', () => attempt(() => runLocalBenchmark(true)));
  el('eval-run').addEventListener('click', () => attempt(async () => {
    showAux(await request('/v1/evaluation/recognition', {
      method: 'POST', body: JSON.stringify({
        dataset_dir: el('eval-data').value.trim(),
        predictions_path: el('eval-predictions').value.trim()
      })
    }));
  }));
  showButtons();if(key)attempt(connect);
})();
