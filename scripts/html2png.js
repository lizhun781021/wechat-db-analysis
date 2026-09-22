#!/usr/bin/env node
/**
 * 微信聊天日报长图生成器
 * ======================
 * 使用 Playwright + 全局 Chrome 将日报 HTML 渲染为整页 PNG 长图。
 *
 * 用法：
 *   node html_to_png.js <input.html> <output.png> [width]
 *
 * 示例：
 *   node html_to_png.js ./daily-reports/2026-08-15/微信聊天日报.html ./daily-reports/2026-08-15/微信聊天日报.png 1280
 */

const path = require('path');

// 全局 node_modules 路径（playwright 通过 npm -g 安装）
const GLOBAL_NODE_MODULES = '/Users/lizhun/.local/share/TeleAgent/runtimes/node/lib/node_modules';
module.paths.push(GLOBAL_NODE_MODULES);
const { chromium } = require('playwright');

async function main() {
  const [inputHtml, outputPng, widthStr] = process.argv.slice(2);
  if (!inputHtml || !outputPng) {
    console.error('用法: node html2png.js <input.html> <output.png> [width]');
    process.exit(1);
  }

  const width = parseInt(widthStr || '1280', 10);
  const inputPath = path.resolve(inputHtml);
  const outputPath = path.resolve(outputPng);
  const fileUrl = 'file://' + inputPath;

  const chromePath = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

  let browser = null;
  try {
    browser = await chromium.launch({
      executablePath: chromePath,
      headless: true,
      args: ['--no-sandbox', '--disable-dev-shm-usage']
    });
    const page = await browser.newPage({ viewport: { width, height: 800 } });

    await page.goto(fileUrl, { waitUntil: 'networkidle' });
    // 等待所有字体和图片加载
    await page.evaluate(() => document.fonts.ready);
    await new Promise(r => setTimeout(r, 1000));

    // Chrome 截图高度上限约 16384px，超出需分段截图拼接
    const fullHeight = await page.evaluate(() => document.body.scrollHeight);
    await page.setViewportSize({ width, height: Math.max(800, fullHeight) });

    const MAX_SHOT_HEIGHT = 14000;
    if (fullHeight <= MAX_SHOT_HEIGHT) {
      await page.screenshot({ path: outputPath, fullPage: true });
    } else {
      // 分段截图保存为临时文件，再用 Python PIL 拼接
      const fs = require('fs');
      const os = require('os');
      const { execSync } = require('child_process');
      const tmpDir = path.join(os.tmpdir(), `wx_stitch_${Date.now()}`);
      fs.mkdirSync(tmpDir, { recursive: true });
      const parts = Math.ceil(fullHeight / MAX_SHOT_HEIGHT);
      const partPaths = [];
      for (let i = 0; i < parts; i++) {
        const partPath = path.join(tmpDir, `part_${String(i).padStart(3,'0')}.png`);
        const clipHeight = Math.min(MAX_SHOT_HEIGHT, fullHeight - i * MAX_SHOT_HEIGHT);
        await page.evaluate((y) => window.scrollTo(0, y), i * MAX_SHOT_HEIGHT);
        await new Promise(r => setTimeout(r, 300));
        await page.screenshot({
          path: partPath,
          clip: { x: 0, y: 0, width, height: clipHeight }
        });
        partPaths.push(partPath);
      }
      // 用 Python PIL 拼接
      const pyScript = path.join(tmpDir, 'stitch.py');
      fs.writeFileSync(pyScript, `
from PIL import Image
import sys, glob, os
parts = sorted(glob.glob(os.path.join('${tmpDir}', 'part_*.png')))
imgs = [Image.open(p) for p in parts]
w = imgs[0].width
h = sum(i.height for i in imgs)
result = Image.new('RGB', (w, h))
y = 0
for img in imgs:
    result.paste(img, (0, y))
    y += img.height
result.save('${outputPath.replace(/'/g, "\\'")}')
`);
      execSync(`python3 "${pyScript}"`, { env: { ...process.env } });
      // 清理临时文件
      for (const pp of partPaths) { try { fs.unlinkSync(pp); } catch(e){} }
      try { fs.unlinkSync(pyScript); } catch(e){}
      try { fs.rmdirSync(tmpDir); } catch(e){}
    }

    const fs = require('fs');
    const sizeKB = (fs.statSync(outputPath).size / 1024).toFixed(1);
    console.log(`长图已生成: ${outputPath}`);
    console.log(`尺寸: ${width}px × ${await page.evaluate(() => document.body.scrollHeight)}px, 大小: ${sizeKB} KB`);
  } catch (err) {
    console.error('长图生成失败:', err.message);
    process.exit(1);
  } finally {
    if (browser) await browser.close();
  }
}

main();