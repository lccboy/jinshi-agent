const tabs = document.querySelectorAll('.tab');
const main = document.getElementById('main');

const views = {
  signal: '实时信号：等待接入 KPL 涨停、题材、板块和策略模型交集。',
  theme: '题材库：等待接入题材列表、细分概念和成分股。',
  sector: '板块强度：等待接入板块排行、子板块强度和成分股。',
  strategy: '策略模型：等待接入 TDX 模型命中、评分和最佳买点。',
  history: '历史选股：等待接入扫描快照和历史归档。',
};

function render(view) {
  main.innerHTML = `<section class="empty-state"><h1>金十DSH 工作台</h1><p>${views[view] || ''}</p></section>`;
}

tabs.forEach((tab) => {
  tab.addEventListener('click', () => {
    tabs.forEach((item) => item.classList.remove('active'));
    tab.classList.add('active');
    render(tab.dataset.view);
  });
});

render('signal');
