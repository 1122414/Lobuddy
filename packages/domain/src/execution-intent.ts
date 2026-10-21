const patterns: readonly [RegExp, boolean][] = [
  [/(打开|启动|运行|帮我开|开一下|帮我打开|帮我启动|帮我运行).{0,8}(桌面|快捷方式|应用|游戏|程序|软件|文件)/iu, true],
  [/(?:^|\s)(?:帮我)?(打开|启动|运行)\S/iu, true],
  [/(在哪|找一下|搜索文件|帮我找|查找|找找|寻找|有没有.*文件).{0,30}(文件|文档|图片|照片|视频|在哪里)/iu, true],
  [/(?:^|\s)(找一下|帮我找|搜索)\S/iu, true],
  [/(在哪|找一下|搜索文件|帮我找|查找|找找|寻找|有没有.*文件).{0,8}(文件|文档|图片|照片|视频)/iu, true],
  [/(关机|重启|注销|锁屏|睡眠|休眠|音量|亮度|蓝牙|WiFi|wifi|网络)/iu, false],
  [/(我喜欢|我是谁|我之前说过|记得我吗|我的名字|我的偏好|我.*喜欢|我.*不喜欢)/iu, false],
];
/** Preserve the legacy best-coverage routing rule, including earlier-pattern ties. */
export function forbidsCommandExecution(prompt: string): boolean {
  let score = -Infinity, forbidden = false;
  for (const [pattern, denies] of patterns) {
    const match = pattern.exec(prompt); if (!match) continue;
    let confidence = Math.min(0.85, [...match[0]].length / Math.max([...prompt.trim()].length, 1) + 0.5);
    if (/桌面|开始菜单|桌面快捷方式/u.test(prompt)) confidence = Math.min(0.95, confidence + 0.15);
    if (/讲个笑话|天气|新闻|帮我写|翻译|解释/u.test(prompt)) confidence = Math.min(0.6, confidence - 0.3);
    confidence = Math.round(confidence * 100) / 100;
    if (confidence > score) { score = confidence; forbidden = denies; }
  }
  return forbidden;
}
