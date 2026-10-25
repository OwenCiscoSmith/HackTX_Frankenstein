const $ = id => document.getElementById(id);
const animals = ['bear','dog','elephant','monkey','alligator','lizard','lion','peacock','fish','narwhal'];
const labels = {torso:['Torso','The foundation','▰'],head:['Head','The personality','◕'],front_legs:['Front legs / arms','A helping hand','⌁'],back_legs:['Back legs','Keep it grounded','⋏'],tail:['Tail','The finishing touch','〰'],wings:['Wings','A little extra possibility','⋈'],horn:['Horn / crest','Top it off','♢']};
const donors = {torso:animals,head:animals,front_legs:animals.filter(a=>a!=='narwhal'),back_legs:animals.filter(a=>a!=='narwhal'),tail:animals.filter(a=>a!=='bear'),wings:['peacock','fish','narwhal'],horn:['peacock','narwhal']};
const optional = new Set(['tail','wings','horn']);
let mode = 'parts', busy = false, specimen = 0;
const title = s => s.charAt(0).toUpperCase()+s.slice(1);
for(const [slot,[name,hint,icon]] of Object.entries(labels)) {
  const row = document.createElement('div'); row.className='part-row';
  const badge=document.createElement('span');badge.className='part-icon';badge.textContent=icon;
  const label=document.createElement('label');label.htmlFor=slot;label.append(name);
  const small=document.createElement('small');small.textContent=hint;label.append(small);
  const select=document.createElement('select');select.id=slot;
  for(const animal of [...(optional.has(slot)?['none']:[]),...donors[slot]]) {
    const option=document.createElement('option');option.value=animal;option.textContent=title(animal);select.append(option);
  }
  select.value=optional.has(slot)?'none':'bear';select.addEventListener('change',updateDonors);
  row.append(badge,label,select);$('selectors').append(row);
}
function selectedAnimals(){return [...new Set(Object.keys(labels).map(s=>$(s).value).filter(a=>a!=='none'))];}
function updateDonors(){const count=selectedAnimals().length;$('donor-count').textContent=`${count} / 3 animals`;$('donor-count').parentElement.classList.toggle('over',count>3);$('donor-dots').replaceChildren(...Array.from({length:count},()=>document.createElement('span')));$('create').disabled=busy||(mode==='parts'&&count>3);if(!busy){$('feedback').textContent=count>3&&mode==='parts'?'Use up to three donor animals to match the creature engine.':'';$('feedback').className=count>3&&mode==='parts'?'error':'';}}
function setMode(next){if(busy)return;mode=next;for(const item of ['parts','prompt']){$(`${item}-tab`).setAttribute('aria-selected',String(item===mode));$(`${item}-tab`).tabIndex=item===mode?0:-1;$(`${item}-panel`).hidden=item!==mode;}updateDonors();}
for(const item of ['parts','prompt']){$(`${item}-tab`).onclick=()=>setMode(item);$(`${item}-tab`).onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();setMode(item==='parts'?'prompt':'parts');$(`${mode}-tab`).focus();}};}
$('example').onclick=()=>{$('prompt').value='A bear with a peacock tail';$('prompt').focus();};
$('shuffle').onclick=()=>{setMode('parts');const pool=['bear','dog','elephant','monkey','alligator','lizard','peacock'].sort(()=>Math.random()-.5).slice(0,3);for(const slot of Object.keys(labels)){const choices=donors[slot].filter(a=>pool.includes(a));$(slot).value=optional.has(slot)&&(Math.random()<.5||!choices.length)?'none':choices[Math.floor(Math.random()*choices.length)];}updateDonors();};
$('create').onclick=async()=>{
  if(busy)return;
  if(mode==='prompt'&&!$('prompt').value.trim()){$('feedback').textContent='Describe your creature first.';$('feedback').className='error';$('prompt').focus();return;}
  const request={parts:Object.keys(labels).filter(s=>$(s).value!=='none').map(slot=>({slot,animal:$(slot).value,count:['front_legs','back_legs','wings'].includes(slot)?2:1}))};
  busy=true;updateDonors();$('shuffle').disabled=true;$('loading').hidden=false;$('feedback').className='';$('feedback').textContent=mode==='prompt'?'Gemini is choosing your creature’s ingredients…':'Assembling your selected animal cutouts…';
  $('warnings').hidden=true;
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),120000);
  try{
    const response=await fetch('/api/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode,request,prompt:$('prompt').value.trim()}),signal:controller.signal});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'Could not create this creature.');
    // Wait for the image before declaring success; retain the previous specimen on errors.
    const image=new Image();image.src=result.image;await image.decode();$('creature').src=result.image;
    const used=[...new Set(result.request.parts.map(p=>p.animal))];specimen++;
    $('creature').alt=`Hybrid creature made from ${used.join(', ')} parts`;$('preview-state').textContent='EXPERIMENT COMPLETE';$('specimen-number').textContent=`SPECIMEN ${String(specimen).padStart(3,'0')}`;
    $('creature-name').textContent=used.map(title).join(' × ');$('creature-detail').textContent='One of a kind. Probably for the best.';$('download').href=result.image;$('download').hidden=false;
    $('warnings').replaceChildren(...result.warnings.map(w=>{const p=document.createElement('p');p.textContent=w;return p;}));$('warnings').hidden=!result.warnings.length;
    $('feedback').textContent='It’s alive! Your creature is ready to save.';
  }catch(error){$('feedback').className='error';$('feedback').textContent=error.name==='AbortError'?'That took too long. Please try again.':error.message;}
  finally{clearTimeout(timeout);busy=false;$('shuffle').disabled=false;$('loading').hidden=true;$('create').disabled=mode==='parts'&&selectedAnimals().length>3;}
};
updateDonors();
