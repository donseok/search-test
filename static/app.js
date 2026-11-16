const $ = id => document.getElementById(id);
let sequence = 0;
function node(tag, text, cls) { const n = document.createElement(tag); n.textContent = text; if (cls) n.className = cls; return n; }
async function run() {
  const version = ++sequence;
  $('results').setAttribute('aria-busy', 'true');
  try {
    const p = new URLSearchParams({q:$('query').value, category:$('category').value, fuzzy:$('fuzzy').checked?'1':'0'});
    const response = await fetch('/api/search?'+p);
    const data = await response.json();
    if(version !== sequence) return;
    if(!response.ok) throw new Error(data.error || '검색에 실패했습니다.');
    $('count').textContent=data.total; $('timing').textContent=`${data.elapsed_ms} ms`;
    $('trace').textContent=data.normalized ? `입력: ${data.query}   →   정규화: ${data.normalized}   ·   오타 허용 ${$('fuzzy').checked?'ON':'OFF'}`:'검색어를 입력하면 일치 방식과 점수를 확인할 수 있습니다.';
    $('results').replaceChildren();
    if(!data.total) $('results').append(node('div','검색 결과가 없습니다. 검색어를 줄이거나 업무 범위를 넓혀 보세요.','empty'));
    data.results.forEach(d=>{
      const card=node('article','', 'card');
      const meta=node('div','', 'meta'); meta.append(node('span',d.category,'category'),node('span',d.id));
      card.append(meta,node('h3',d.title),node('p',d.body));
      const bottom=node('div','','card-bottom'); bottom.append(node('span',`${d.reason}${d.matched?' · '+d.matched:''}`),node('strong',d.score?`${d.score}점`:'')); card.append(bottom); $('results').append(card);
    });
  } catch(e) { if(version===sequence) { $('count').textContent='—'; $('timing').textContent=''; $('trace').textContent='검색 실패'; $('results').replaceChildren(node('div',e.message,'empty')); } }
  finally { if(version===sequence) $('results').setAttribute('aria-busy','false'); }
}
['프로젝트','프 로 젝 트','Project','프로젝','후로젝트','coil','소둔'].forEach(q=>{const b=node('button',q);b.type='button';b.onclick=()=>{$('query').value=q;run();};$('examples').append(b);});
$('search-form').onsubmit=e=>{e.preventDefault();run();}; $('category').onchange=run; $('fuzzy').onchange=run;
let timer; $('query').oninput=()=>{clearTimeout(timer);timer=setTimeout(run,250);}; run();
