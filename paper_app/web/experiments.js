"use strict";
const $ = id => document.getElementById(id);
const status = $('status'), picker = $('experiments');
for (const select of document.querySelectorAll('.audience')) {
  for (const [value, label] of [['owner','Owner only'], ['users','Trusted humans'], ['local','Trusted humans and local AI'], ['all','All trusted accounts']]) {
    const option = document.createElement('option'); option.value = value; option.textContent = label; select.append(option);
  }
}
function text(tag, content, parent) { const el = document.createElement(tag); el.textContent = content; parent.append(el); return el; }
function submit(id, action) { $(id).addEventListener('submit', async event => {event.preventDefault(); try {await action(event.currentTarget); status.textContent = 'Saved.';} catch (error) {status.textContent = error.message;}}); }
function names(s) {return s.split(',').map(x => x.trim()).filter(Boolean);}
let active = null;
async function refresh() {
  const result = await api('experiments'); picker.replaceChildren();
  const empty = document.createElement('option'); empty.value = ''; empty.textContent = 'Choose'; picker.append(empty);
  for (const item of result.experiments) {const option = document.createElement('option'); option.value = item.id; option.textContent = `${item.title} (#${item.id})`; picker.append(option);}
  picker.value = active || '';
  if (picker.value) await showExperiment(); else $('detail').hidden = true;
}
async function showExperiment() {
  active = Number(picker.value); if (!active) {$('detail').hidden = true; return;}
  const result = await api(`experiment-detail?id=${active}`); $('detail').hidden = false;
  $('experiment-title').textContent = `${result.experiment.title} (#${active}, revision ${result.experiment.revision})`;
  $('experiment-description').textContent = result.experiment.description;
  const runs = $('runs'), runSelect = $('run-select'); runs.replaceChildren(); runSelect.replaceChildren();
  const empty = document.createElement('option'); empty.value = ''; empty.textContent = 'Experiment level'; runSelect.append(empty);
  for (const run of result.runs) {text('p', `${run.title} (#${run.id}) · ${run.status}`, runs); const opt = document.createElement('option'); opt.value = run.id; opt.textContent = run.title; runSelect.append(opt);}
  const items = $('items'); items.replaceChildren();
  for (const item of result.items) {const box = text('div', `${item.kind}: ${item.title} (#${item.id}, revision ${item.revision})`, items); for (const version of item.versions) {const line = text('p', `v${version.number} · ${version.description} ${version.external_ref}`, box); if (version.sha256) {const link = text('a', `Download ${version.filename}`, line); link.href = `/research-versions/${version.id}/file`;}}}
}
picker.addEventListener('change', () => showExperiment().catch(e => {status.textContent = e.message;}));
submit('experiment-form', async form => {const f = form.elements; const data = {title:f.title.value,description:f.description.value,audience:f.audience.value,paper_id:f.paper_id.value ? Number(f.paper_id.value) : null}; const result = await api('experiments',data); active = result.id; form.reset(); await refresh();});
submit('run-form', async form => {const f=form.elements; await api('experiment-runs',{experiment_id:active,title:f.title.value,description:f.description.value,audience:f.audience.value}); form.reset(); await refresh();});
submit('item-form', async form => {const f=form.elements, file=f.file.files[0]; const data={experiment_id:active,run_id:f.run_id.value ? Number(f.run_id.value):null,kind:f.kind.value,title:f.title.value,description:f.description.value,audience:f.audience.value,external_ref:f.external_ref.value}; if(f.id.value){data.id=Number(f.id.value);data.revision=Number(f.revision.value);} if(file){data.filename=file.name;const response=await fetch('/api/research-upload',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Research-Metadata':encodeURIComponent(JSON.stringify(data))},body:file});const result=await response.json();if(!response.ok) throw new Error(result.error || 'Upload failed.');}else await api('research-items',data);form.reset();await refresh();});
submit('grant-form', async form => {const f=form.elements;await api('research-grants',{kind:f.kind.value,id:Number(f.id.value),readers:names(f.readers.value),editors:names(f.editors.value)});await refresh();});
async function loadTools(){const result=await api('research-tools');for(const tool of result.tools) text('p',`${tool.name} ${tool.version} · ${tool.description}`, $('tools'));for(const tool of result.host_tools) text('p',`${tool.name}: ${tool.available ? tool.version || 'available' : 'not installed'}`, $('host-tools'));}
Promise.all([refresh(),loadTools()]).catch(error => {status.textContent=error.message;});
