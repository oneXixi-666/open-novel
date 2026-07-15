import type { BookCreationOptions, GenreOption, PlatformStyleOption } from "../types";

export const platformStyleOptions: PlatformStyleOption[] = [
  {
    id: "generic-web-serial",
    label: "通用网文连载",
    platform: "generic",
    status: "active",
    genres: ["web-serial"],
    summary: "适合尚未锁定平台的新书，强调章节承诺、冲突推进和章尾追读。"
  },
  {
    id: "fanqie-xuanhuan-upgrade",
    label: "番茄玄幻升级流",
    platform: "fanqie",
    status: "candidate",
    genres: ["xuanhuan", "upgrade", "web-serial"],
    summary: "强调压迫到反击、升级代价、爽点兑现和章尾追读。"
  },
  {
    id: "urban-emotion-suspense",
    label: "都市情绪悬疑",
    platform: "generic",
    status: "candidate",
    genres: ["urban", "emotion", "suspense"],
    summary: "强调现实压力、关系潜台词、公平线索和克制情绪。"
  },
  {
    id: "female-romance-growth",
    label: "女频情感成长",
    platform: "generic",
    status: "candidate",
    genres: ["romance", "growth", "relationship"],
    summary: "强调关系递进、边界感、互动因果和人物成长。"
  },
  {
    id: "qidian-xianxia-longform",
    label: "起点仙侠长篇",
    platform: "qidian",
    status: "planned",
    genres: ["xianxia", "cultivation", "longform"],
    summary: "适合宗门、体系和长期升级线，强调阶段目标与突破代价。"
  },
  {
    id: "douyin-micro-drama-reversal",
    label: "短剧高反转",
    platform: "douyin",
    status: "planned",
    genres: ["micro-drama", "reversal", "revenge", "high-hook"],
    summary: "适合高频钩子、强反转和复仇线，强调短节奏推进。"
  },
  {
    id: "jjwxc-romance-slowburn",
    label: "晋江慢热情感",
    platform: "jjwxc",
    status: "planned",
    genres: ["romance", "slowburn", "relationship"],
    summary: "适合慢热、拉扯和细腻成长，强调关系递进与情绪转折。"
  }
];

export const genreOptions: GenreOption[] = [
  { label: "都市悬疑", value: "都市悬疑", platformHints: ["generic", "fanqie"] },
  { label: "都市情感", value: "都市情感", platformHints: ["generic", "jjwxc"] },
  { label: "玄幻升级", value: "玄幻升级", platformHints: ["fanqie", "qidian"] },
  { label: "仙侠修真", value: "仙侠修真", platformHints: ["qidian"] },
  { label: "科幻冒险", value: "科幻冒险", platformHints: ["generic", "qidian"] },
  { label: "女频成长", value: "女频成长", platformHints: ["generic", "jjwxc"] },
  { label: "短剧复仇", value: "短剧复仇", platformHints: ["douyin", "fanqie"] },
  { label: "职场商战", value: "职场商战", platformHints: ["generic"] }
];

export const platformLabels: Record<string, string> = {
  generic: "跨平台",
  fanqie: "番茄",
  qidian: "起点",
  douyin: "抖音短剧",
  jjwxc: "晋江"
};

export const bookCreationOptions: BookCreationOptions = {
  platformStyles: platformStyleOptions,
  genres: genreOptions,
  platformLabels
};

export function defaultGenreForStyle(style: PlatformStyleOption) {
  const matched = genreOptions.find((genre) => genre.platformHints.includes(style.platform));
  return matched?.value ?? genreOptions[0].value;
}
