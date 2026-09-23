import { BASE_URL } from '../runtime.js';

export const DEMO_DATE = '2026-09-01T05:00:00+08:00';
export const asset = name => `${BASE_URL}demo/${name}.svg`;
const families = [
  ['shuma', '数码配件', 'headphones', ['无线头戴耳机', '降噪通勤耳机', '轻量音乐耳机']],
  ['fuzhuan', '出行穿搭', 'bag', ['帆布通勤包', '轻量旅行包', '日常斜挎包']],
  ['jiaju', '家居照明', 'lamp', ['暖光阅读灯', '桌面氛围灯', '床头阅读灯']],
  ['meir', '美容护理', 'bottle', ['旅行分装瓶', '按压洗护瓶', '磨砂护理瓶']],
  ['muying', '母婴玩具', 'blocks', ['几何积木套装', '木质堆叠玩具', '色彩认知积木']],
  ['qimo', '车内收纳', 'organizer', ['便携收纳盒', '模块整理盒', '车载储物盒']],
  ['shipin', '厨房用品', 'cup', ['随行保温杯', '咖啡随行杯', '户外饮水杯']],
  ['qita', '户外生活', 'backpack', ['轻量徒步背包', '城市出行背包', '周末旅行背包']],
];

// 全部为人工构造的界面样本：不是爬取结果，不使用真实品牌、ASIN 或销量声明。
export const products = families.flatMap(([group, , icon, names], familyIndex) =>
  Array.from({ length: 12 }, (_, i) => {
    const currency = ['USD', 'JPY', 'GBP', 'SGD'][i % 4];
    const price = [24.9 + i, 2800 + i * 100, 18.5 + i, 32 + i][i % 4];
    return {
      asin: `DE${String(familyIndex * 12 + i + 1).padStart(8, '0')}`,
      title: `${names[i % names.length]} · ${['雾绿', '砂岩', '暖白', '石墨'][i % 4]}款`,
      group, image_url: asset(icon), url: asset(icon), price, currency,
      price_display: `${currency} ${price.toFixed(2)}`, rating: Number((4.3 + (i % 6) / 10).toFixed(1)),
      review_count: i % 3 === 0 ? 25 + i * 4 : 120 + i * 83, sales: `${100 + i * 50}+（模拟值）`,
    };
  }));

export const recommendations = {
  snapshot_id: 'portfolio-demo-v1', presentation_version: 1, generated_at: DEMO_DATE,
  update_status: 'demo', partial: false, is_stale: false,
  evidence: { scope: '人工编写的选品样例，用于展示数据字段、推荐说明和类别切换；未进行实时市场采集。',
    sampled_categories: 8, available_categories: 8, candidate_products: products.length, sources: [] },
  categories: families.map(([group, title], index) => ({
    candidate_id: group, keyword: group, title, status: 'ok',
    products: products.filter(item => item.group === group).slice(0, 5),
    answer: [
      '此类样例展示评分、评论量与不同币种价格的联合比较。真实版本会先采集候选商品，再依据公开购买提示和评论量筛选；不会仅凭模型生成的主题宣称市场正在增长。',
      '示例中保留多种规格，帮助对比同一品类的价格区间。正式推荐会按 ASIN 跨类别去重，并结合近 7 天的历史优先补入未推荐商品；候选不足时会明确说明。',
      '这组示例用于展示产品图、推荐依据与来源信息的组合。实际系统会记录采集时间和数据缺口；定时更新失败时保留上期完整快照，页面刷新只读取已保存结果。',
    ][index % 3],
    selection_reason: '演示数据，不构成选品建议；切换类别可查看不同场景的页面效果。',
  })),
};

export function productPage(url) {
  const group = url.searchParams.get('subCategory') || 'all';
  const page = Math.max(1, Number(url.searchParams.get('page')) || 1);
  let pool = products.filter(item => group === 'all' || item.group === group);
  if (url.searchParams.get('category') === 'niche') pool = pool.filter(item => item.review_count <= 100);
  const size = 12;
  return { products: pool.slice((page - 1) * size, page * size), page, pages_scanned: 1,
    next_page: page * size < pool.length ? page + 1 : null, category: url.searchParams.get('category') || 'hot',
    sub_category: group, period: 'current', partial: false, fetched_at: DEMO_DATE, from_cache: true,
    warnings: ['商品名称、价格、评分和购买提示均为模拟数据；图片为项目内原创 SVG 示意图。'],
  };
}

export const demoImages = Array.from({ length: 4 }, (_, index) => ({
  index, name: `studio-demo-${index + 1}.svg`, url: asset(`scene-${index + 1}`),
}));
export function imageJob(id = 'example', prompt = '一只产品，四种光影。白底、暖阳、森林与几何空间。', mode = 'product') {
  return { id, created_at: DEMO_DATE, prompt, mode, references: [], status: 'completed',
    images: demoImages, can_retry_save: false,
    reply: '以下为预制的四张 SVG 场景示意图，用于演示放大和下载，不是 AI 现场生成。提示词和上传图片不会发送到任何服务器。' };
}

export function answerFor(question) {
  const topics = [
    { match: /FBA|物流|配送|仓储/i, title: 'FBA 费用结构', text: '分析 FBA 成本时，可以先分开记录配送、仓储、入库及其他可能产生的费用，再结合站点、尺寸、重量和库存周转做比较。[资料 1]\n\n具体收费标准会变化，完整版应检索带发布日期的资料，并核对官方费率表。展示版不提供实时金额。' },
    { match: /VAT|税|欧洲/i, title: '欧洲站税务资料阅读', text: '可以先整理销售国家、库存所在地和业务主体，再核对各地的注册、申报要求。[资料 1]\n\n这里展示的是资料组织方式，不是针对个人业务的税务结论。实际处理需要最新官方资料及专业确认。' },
    { match: /品牌|商标/i, title: '品牌材料整理', text: '品牌资料可按商标信息、权利人、产品与包装展示、主体联系方式分别整理。[资料 1]\n\n实际提交材料应以当前站点的官方要求为准。演示没有在线查询品牌审核规则。' },
    { match: /广告|新品/i, title: '新品广告分析框架', text: '先明确目标，再检查商品详情页与转化基础；测试时分组观察曝光、点击、花费和订单，避免只看单一指标。[资料 1]\n\n预算和投放策略需要结合实际经营数据。此处仅演示带引用的 Markdown 回答。' },
  ];
  const topic = topics.find(item => item.match.test(question));
  if (!topic) return { answer: '**这是离线交互展示。**\n\n当前问题没有对应的预置回答，我不会把固定文本伪装成模型推理结果。\n\n你可以试试：\n- 亚马逊 FBA 物流有哪些主要费用？\n- 欧洲站 VAT 注册和申报要注意什么？\n- 品牌备案需要准备哪些材料？\n- 新品上架后如何规划站内广告？\n\n本地完整版会执行问题改写、向量召回、精排和模型回答。', sources: [] };
  return { answer: `> 预置演示回答 · 未调用模型或实时检索\n\n### ${topic.title}\n\n${topic.text}`,
    sources: [{ id: 1, title: `${topic.title}（演示资料卡）`, source: '项目内人工编写样例',
      category: '演示资料', excerpt: '仅用于演示引用卡片的交互；不来自正式知识库，不代表官方政策。' }] };
}
