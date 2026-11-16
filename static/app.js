// MES 검색 실험실 - 화면 동작
// 검색 로직은 서버(app.py의 search 함수)에 있고, 이 파일은 입력을 보내고 결과를 그리기만 합니다.

const $ = id => document.getElementById(id);

// 요청 번호. 빠르게 타이핑하면 응답이 순서 없이 도착할 수 있으므로,
// 가장 마지막에 보낸 요청의 응답만 화면에 그립니다.
let sequence = 0;

// 태그를 만들고 글자는 textContent 로 넣습니다 (innerHTML 을 쓰지 않아 HTML 삽입 공격 방지).
function node(tag, text, cls) {
  const n = document.createElement(tag);
  n.textContent = text;
  if (cls) n.className = cls;
  return n;
}

// 검색 결과 카드 1장
function card(d) {
  const el = node('article', '', 'card');
  const meta = node('div', '', 'meta');
  meta.append(node('span', d.category, 'category'), node('span', d.id));
  el.append(meta, node('h3', d.title), node('p', d.body));
  const bottom = node('div', '', 'card-bottom');
  // 예: "정확·정규화 일치 · RAL9006   100점"
  bottom.append(node('span', `${d.reason}${d.matched ? ' · ' + d.matched : ''}`),
                node('strong', d.score ? `${d.score}점` : ''));
  el.append(bottom);
  return el;
}

async function run() {
  const version = ++sequence;
  $('results').setAttribute('aria-busy', 'true');
  try {
    // 1) 서버에 검색 요청: /api/search?q=...&category=...&fuzzy=1
    const p = new URLSearchParams({
      q: $('query').value,
      category: $('category').value,
      fuzzy: $('fuzzy').checked ? '1' : '0',
    });
    const response = await fetch('/api/search?' + p);
    const data = await response.json();
    if (version !== sequence) return;  // 더 새로운 요청이 있으면 이 응답은 버림
    if (!response.ok) throw new Error(data.error || '검색에 실패했습니다.');

    // 2) 건수·시간·정규화 결과 표시. "입력 → 정규화"를 보여 주어 서버가 무엇으로 비교했는지 확인 가능
    $('count').textContent = data.total;
    $('timing').textContent = `${data.elapsed_ms} ms`;
    $('trace').textContent = $('query').value.trim()
      ? `입력: ${data.query}   →   정규화: ${data.normalized || '(빈 값)'}   ·   오타 허용 ${$('fuzzy').checked ? 'ON' : 'OFF'}`
      : '검색어를 입력하면 일치 방식과 점수를 확인할 수 있습니다.';

    // 3) 결과 카드 그리기 (서버가 이미 점수순으로 정렬해서 보냄)
    $('results').replaceChildren();
    if (!data.total) $('results').append(node('div', '검색 결과가 없습니다. 검색어를 줄이거나 업무 범위를 넓혀 보세요.', 'empty'));
    data.results.forEach(d => $('results').append(card(d)));
  } catch (e) {
    if (version === sequence) {
      $('count').textContent = '—';
      $('timing').textContent = '';
      $('trace').textContent = '검색 실패';
      $('results').replaceChildren(node('div', e.message, 'empty'));
    }
  } finally {
    if (version === sequence) $('results').setAttribute('aria-busy', 'false');
  }
}

// 예시 검색어 버튼
['프로젝트', '프 로 젝 트', 'Project', '프로젝', '후로젝트', 'coil', '소둔', 'RAL_9006', 'ral-9006', 'rAl 9006'].forEach(q => {
  const b = node('button', q);
  b.type = 'button';
  b.onclick = () => { $('query').value = q; run(); };
  $('examples').append(b);
});

$('search-form').onsubmit = e => { e.preventDefault(); run(); };
$('category').onchange = run;
$('fuzzy').onchange = run;

// 타이핑할 때마다 바로 요청하지 않고, 입력이 0.25초 멈추면 검색 (debounce)
let timer;
$('query').oninput = () => { clearTimeout(timer); timer = setTimeout(run, 250); };

run();  // 첫 화면: 전체 문서 표시
