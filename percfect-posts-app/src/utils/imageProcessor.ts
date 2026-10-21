import { WatermarkSettings } from '../types.ts';

export interface ProcessImageOptions {
  imageUrl: string;
  watermark: WatermarkSettings;
  upscaleFactor?: 1 | 2 | 4;
  aspectRatio?: 'original' | '1:1' | '4:5' | '9:16' | '16:9';
  title?: string;
  disclaimer?: string;
}

export async function processCanvasImage(options: ProcessImageOptions): Promise<string> {
  const {
    imageUrl,
    watermark,
    upscaleFactor = 1,
    aspectRatio = 'original',
    title = '',
    disclaimer = '',
  } = options;

  return new Promise((resolve, reject) => {
    const mainImg = new Image();
    mainImg.crossOrigin = 'anonymous';

    mainImg.onload = async () => {
      try {
        let srcX = 0;
        let srcY = 0;
        let srcWidth = mainImg.naturalWidth;
        let srcHeight = mainImg.naturalHeight;

        // Calculate aspect ratio crop if requested
        if (aspectRatio !== 'original') {
          let targetRatio = 1;
          if (aspectRatio === '1:1') targetRatio = 1;
          if (aspectRatio === '4:5') targetRatio = 4 / 5;
          if (aspectRatio === '9:16') targetRatio = 9 / 16;
          if (aspectRatio === '16:9') targetRatio = 16 / 9;

          const currentRatio = srcWidth / srcHeight;
          if (currentRatio > targetRatio) {
            // Image is wider than target
            const newWidth = srcHeight * targetRatio;
            srcX = (srcWidth - newWidth) / 2;
            srcWidth = newWidth;
          } else {
            // Image is taller than target
            const newHeight = srcWidth / targetRatio;
            srcY = (srcHeight - newHeight) / 2;
            srcHeight = newHeight;
          }
        }

        const canvas = document.createElement('canvas');
        const targetWidth = Math.round(srcWidth * upscaleFactor);
        const targetHeight = Math.round(srcHeight * upscaleFactor);
        canvas.width = targetWidth;
        canvas.height = targetHeight;

        const ctx = canvas.getContext('2d');
        if (!ctx) {
          throw new Error('Canvas 2D context unavailable');
        }

        // Enable high quality image scaling
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';

        // Draw cropped & upscaled base image
        ctx.drawImage(
          mainImg,
          srcX,
          srcY,
          srcWidth,
          srcHeight,
          0,
          0,
          targetWidth,
          targetHeight
        );

        // Apply sharpening filter if upscaled
        if (upscaleFactor > 1) {
          try {
            applySharpeningFilter(ctx, targetWidth, targetHeight, 0.25);
          } catch (e) {
            // Canvas may be tainted if external image lacks CORS headers; continue safely
          }
        }

        // Draw Watermark & Stamps if enabled
        if (watermark.enabled) {
          const margin = (watermark.margin || 24) * upscaleFactor;

          // 1. Logo Stamp
          if (
            (watermark.type === 'logo' || watermark.type === 'both') &&
            watermark.logoUrl
          ) {
            await drawLogo(ctx, watermark, targetWidth, targetHeight, margin);
          }

          // 2. Title Stamp (Top or Header banner)
          const activeTitle = title || watermark.titleText;
          if (activeTitle) {
            drawTitleBanner(ctx, activeTitle, watermark, targetWidth, margin, upscaleFactor);
          }

          // 3. Disclaimer Stamp (Bottom footer strip)
          const activeDisclaimer = disclaimer || watermark.disclaimerText;
          if (activeDisclaimer) {
            drawDisclaimerBar(
              ctx,
              activeDisclaimer,
              watermark,
              targetWidth,
              targetHeight,
              upscaleFactor
            );
          }

          // 4. Text Watermark / Author handle
          if (
            (watermark.type === 'text' || watermark.type === 'both') &&
            watermark.watermarkText
          ) {
            drawTextWatermark(ctx, watermark, targetWidth, targetHeight, margin, upscaleFactor);
          }
        }

        resolve(canvas.toDataURL('image/jpeg', 0.92));
      } catch (err) {
        reject(err);
      }
    };

    mainImg.onerror = (e) => reject(new Error('Failed to load image for processing: ' + e));
    mainImg.src = imageUrl;
  });
}

async function drawLogo(
  ctx: CanvasRenderingContext2D,
  watermark: WatermarkSettings,
  canvasW: number,
  canvasH: number,
  margin: number
): Promise<void> {
  return new Promise((resolve) => {
    const logoImg = new Image();
    logoImg.crossOrigin = 'anonymous';
    logoImg.onload = () => {
      const maxDim = (Math.min(canvasW, canvasH) * (watermark.logoScale || 15)) / 100;
      const aspect = logoImg.naturalWidth / logoImg.naturalHeight;
      let logoW = maxDim;
      let logoH = maxDim / aspect;
      if (aspect < 1) {
        logoH = maxDim;
        logoW = maxDim * aspect;
      }

      let x = canvasW - logoW - margin;
      let y = canvasH - logoH - margin;

      if (watermark.position === 'top-left') {
        x = margin;
        y = margin + 40;
      } else if (watermark.position === 'top-right') {
        x = canvasW - logoW - margin;
        y = margin + 40;
      } else if (watermark.position === 'bottom-left') {
        x = margin;
        y = canvasH - logoH - margin - 30;
      } else if (watermark.position === 'center') {
        x = (canvasW - logoW) / 2;
        y = (canvasH - logoH) / 2;
      }

      ctx.save();
      ctx.globalAlpha = watermark.logoOpacity || 0.85;

      // Soft drop shadow for logo
      ctx.shadowColor = 'rgba(0,0,0,0.5)';
      ctx.shadowBlur = 12;
      ctx.shadowOffsetX = 2;
      ctx.shadowOffsetY = 2;

      ctx.drawImage(logoImg, x, y, logoW, logoH);
      ctx.restore();
      resolve();
    };
    logoImg.onerror = () => resolve(); // continue without crashing if logo fails
    logoImg.src = watermark.logoUrl;
  });
}

function drawTitleBanner(
  ctx: CanvasRenderingContext2D,
  title: string,
  watermark: WatermarkSettings,
  canvasW: number,
  margin: number,
  scale: number
) {
  ctx.save();
  const fontSize = Math.max(16, Math.round(22 * scale));
  ctx.font = `700 ${fontSize}px 'Plus Jakarta Sans', sans-serif`;

  const textMetrics = ctx.measureText(title.toUpperCase());
  const paddingX = 16 * scale;
  const paddingY = 8 * scale;
  const bannerW = textMetrics.width + paddingX * 2;
  const bannerH = fontSize + paddingY * 2;
  const x = margin;
  const y = margin;

  // Background badge
  ctx.fillStyle = watermark.backgroundColor || 'rgba(15, 23, 42, 0.85)';
  ctx.beginPath();
  ctx.roundRect(x, y, bannerW, bannerH, 6 * scale);
  ctx.fill();

  // Subtle border
  ctx.strokeStyle = 'rgba(99, 102, 241, 0.6)';
  ctx.lineWidth = 1.5 * scale;
  ctx.stroke();

  // Text
  ctx.fillStyle = watermark.textColor || '#FFFFFF';
  ctx.textBaseline = 'middle';
  ctx.fillText(title.toUpperCase(), x + paddingX, y + bannerH / 2);
  ctx.restore();
}

function drawDisclaimerBar(
  ctx: CanvasRenderingContext2D,
  disclaimer: string,
  watermark: WatermarkSettings,
  canvasW: number,
  canvasH: number,
  scale: number
) {
  ctx.save();
  const fontSize = Math.max(11, Math.round(13 * scale));
  ctx.font = `500 ${fontSize}px 'Plus Jakarta Sans', sans-serif`;

  const barH = Math.round(28 * scale);
  const y = canvasH - barH;

  // Dark translucent footer bar
  ctx.fillStyle = 'rgba(2, 6, 23, 0.85)';
  ctx.fillRect(0, y, canvasW, barH);

  // Top border of bar
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.1)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, y);
  ctx.lineTo(canvasW, y);
  ctx.stroke();

  // Disclaimer text
  ctx.fillStyle = '#94a3b8';
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'center';
  ctx.fillText(disclaimer, canvasW / 2, y + barH / 2);
  ctx.restore();
}

function drawTextWatermark(
  ctx: CanvasRenderingContext2D,
  watermark: WatermarkSettings,
  canvasW: number,
  canvasH: number,
  margin: number,
  scale: number
) {
  ctx.save();
  const fontSize = Math.max(13, Math.round((watermark.fontSize || 16) * scale));
  ctx.font = `600 ${fontSize}px 'Plus Jakarta Sans', sans-serif`;

  const textMetrics = ctx.measureText(watermark.watermarkText);
  let x = canvasW - textMetrics.width - margin;
  let y = canvasH - margin - 35 * scale; // above footer if any

  if (watermark.position === 'bottom-left') {
    x = margin;
  } else if (watermark.position === 'top-left') {
    x = margin;
    y = margin + 80 * scale;
  } else if (watermark.position === 'top-right') {
    x = canvasW - textMetrics.width - margin;
    y = margin + 80 * scale;
  }

  // Pill backdrop
  const padX = 12 * scale;
  const padY = 6 * scale;
  const pillW = textMetrics.width + padX * 2;
  const pillH = fontSize + padY * 2;

  ctx.fillStyle = 'rgba(15, 23, 42, 0.7)';
  ctx.beginPath();
  ctx.roundRect(x - padX, y - fontSize, pillW, pillH, 9999);
  ctx.fill();

  ctx.fillStyle = watermark.textColor || '#FFFFFF';
  ctx.textBaseline = 'bottom';
  ctx.fillText(watermark.watermarkText, x, y);
  ctx.restore();
}

function applySharpeningFilter(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  mix: number = 0.2
) {
  const imgData = ctx.getImageData(0, 0, w, h);
  const d = imgData.data;
  const buff = new Uint8ClampedArray(d);

  // Basic 3x3 unsharp convolution kernel
  // [  0, -1,  0 ]
  // [ -1,  5, -1 ]
  // [  0, -1,  0 ]
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const idx = (y * w + x) * 4;
      for (let c = 0; c < 3; c++) {
        const top = ((y - 1) * w + x) * 4 + c;
        const bottom = ((y + 1) * w + x) * 4 + c;
        const left = (y * w + (x - 1)) * 4 + c;
        const right = (y * w + (x + 1)) * 4 + c;
        const center = idx + c;

        const sharp = 5 * buff[center] - buff[top] - buff[bottom] - buff[left] - buff[right];
        d[idx + c] = Math.min(255, Math.max(0, buff[center] * (1 - mix) + sharp * mix));
      }
    }
  }

  ctx.putImageData(imgData, 0, 0);
}
