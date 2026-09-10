(() => {
  const canvas = document.createElement('canvas');
  canvas.id = 'orange-theme-fx-canvas';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.appendChild(canvas);

  const ctx = canvas.getContext('2d');
  let raf = null;
  let activeEffect = null;
  let lastFrame = 0;
  let dpr = 1;
  let width = 0;
  let height = 0;
  let matrixColumns = [];
  let stars = [];
  let sparkles = [];

  const MATRIX_GLYPHS = 'ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾗﾘﾙﾚﾛ0123456789+-<>[]{}';

  function prefersReducedMotion() {
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || document.documentElement.dataset.orangeMotion === 'reduced';
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.max(1, Math.round(width * dpr));
    canvas.height = Math.max(1, Math.round(height * dpr));
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    seedForEffect(activeEffect);
  }

  function randomGlyph() {
    return MATRIX_GLYPHS[Math.floor(Math.random() * MATRIX_GLYPHS.length)];
  }

  function seedMatrix() {
    // Wider spacing + larger type keeps the rain legible instead of becoming texture.
    const spacing = 31;
    const count = Math.ceil(width / spacing);
    matrixColumns = Array.from({ length: count }, (_, i) => ({
      x: i * spacing + 8 + Math.random() * 10,
      y: -Math.random() * height,
      speed: 24 + Math.random() * 34,
      length: 7 + Math.floor(Math.random() * 9),
      glyphs: Array.from({ length: 20 }, randomGlyph),
      mutation: Math.random() * 1000,
    }));
  }

  function seedStars() {
    const count = Math.max(70, Math.min(170, Math.round((width * height) / 11000)));
    stars = Array.from({ length: count }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      size: .55 + Math.random() * 1.45,
      phase: Math.random() * Math.PI * 2,
      speed: .18 + Math.random() * .42,
      warm: Math.random() < .18,
      cross: Math.random() < .07,
    }));
  }

  function seedSparkles() {
    // Sparse and slow: individual twinkles, not a repeating wallpaper pattern.
    const count = Math.max(8, Math.min(16, Math.round((width * height) / 100000)));
    sparkles = Array.from({ length: count }, () => ({
      x: 30 + Math.random() * Math.max(1, width - 60),
      y: 30 + Math.random() * Math.max(1, height - 60),
      size: 1.6 + Math.random() * 3.2,
      phase: Math.random() * Math.PI * 2,
      speed: .08 + Math.random() * .12,
      drift: 2 + Math.random() * 5,
      pink: Math.random() < .42,
    }));
  }

  function seedForEffect(effect) {
    if (!ctx || !effect) return;
    ctx.clearRect(0, 0, width, height);
    if (effect === 'cyber') seedMatrix();
    if (effect === 'midnight') seedStars();
    if (effect === 'princess') seedSparkles();
  }

  function drawMatrix(dt) {
    // Faster fade leaves crisp glyphs without a smeared green curtain.
    ctx.fillStyle = 'rgba(1, 6, 3, 0.18)';
    ctx.fillRect(0, 0, width, height);
    ctx.font = '16px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    for (const col of matrixColumns) {
      col.y += col.speed * dt;
      col.mutation += dt * 1000;
      if (col.mutation > 150) {
        col.mutation = 0;
        const index = Math.floor(Math.random() * col.glyphs.length);
        col.glyphs[index] = randomGlyph();
      }

      for (let i = 0; i < col.length; i++) {
        const y = col.y - i * 22;
        if (y < -28 || y > height + 28) continue;
        const fade = 1 - i / col.length;
        if (i === 0) {
          ctx.shadowBlur = 8;
          ctx.shadowColor = 'rgba(198,255,216,.9)';
          ctx.fillStyle = 'rgba(228,255,236,.98)';
        } else {
          ctx.shadowBlur = i < 3 ? 4 : 0;
          ctx.shadowColor = 'rgba(57,255,136,.62)';
          ctx.fillStyle = `rgba(57,255,136,${Math.max(.06, fade * .64)})`;
        }
        ctx.fillText(col.glyphs[i % col.glyphs.length], col.x, y);
      }
      ctx.shadowBlur = 0;

      if (col.y - col.length * 22 > height + 50) {
        col.y = -50 - Math.random() * height * .7;
        col.speed = 24 + Math.random() * 34;
        col.length = 7 + Math.floor(Math.random() * 9);
      }
    }
  }

  function drawStars(time) {
    ctx.clearRect(0, 0, width, height);
    for (const star of stars) {
      const alpha = .22 + (.78 * (.5 + .5 * Math.sin(time * star.speed + star.phase)));
      const color = star.warm ? `rgba(236,213,143,${alpha})` : `rgba(225,233,255,${alpha * .9})`;
      ctx.fillStyle = color;
      ctx.shadowBlur = star.cross ? 8 : 3;
      ctx.shadowColor = color;
      ctx.beginPath();
      ctx.arc(star.x, star.y, star.size, 0, Math.PI * 2);
      ctx.fill();
      if (star.cross && alpha > .65) {
        ctx.fillRect(star.x - star.size * 3, star.y - .45, star.size * 6, .9);
        ctx.fillRect(star.x - .45, star.y - star.size * 3, .9, star.size * 6);
      }
    }
    ctx.shadowBlur = 0;
  }

  function drawSparkles(time) {
    ctx.clearRect(0, 0, width, height);
    for (const sparkle of sparkles) {
      const wave = .5 + .5 * Math.sin(time * sparkle.speed + sparkle.phase);
      const alpha = Math.pow(wave, 4) * .62;
      if (alpha < .025) continue;
      const y = sparkle.y + Math.sin(time * .08 + sparkle.phase) * sparkle.drift;
      const color = sparkle.pink ? `rgba(185,52,117,${alpha})` : `rgba(255,244,249,${alpha})`;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.shadowBlur = 5;
      ctx.shadowColor = color;
      ctx.beginPath();
      ctx.moveTo(sparkle.x - sparkle.size * 2.1, y);
      ctx.lineTo(sparkle.x + sparkle.size * 2.1, y);
      ctx.moveTo(sparkle.x, y - sparkle.size * 2.1);
      ctx.lineTo(sparkle.x, y + sparkle.size * 2.1);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(sparkle.x, y, sparkle.size * .5, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
    }
    ctx.shadowBlur = 0;
  }

  function drawArcade(time) {
    ctx.clearRect(0, 0, width, height);
    const horizon = height * .59;

    const sky = ctx.createLinearGradient(0, 0, 0, height);
    sky.addColorStop(0, '#070014');
    sky.addColorStop(.55, '#23003b');
    sky.addColorStop(1, '#06000d');
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, width, height);

    // Large striped synth sun gives the theme an immediate 80s read.
    const sunX = width * .5;
    const sunY = horizon - Math.min(80, height * .08);
    const sunR = Math.max(70, Math.min(145, width * .085));
    const sunGradient = ctx.createLinearGradient(0, sunY - sunR, 0, sunY + sunR);
    sunGradient.addColorStop(0, '#ffd166');
    sunGradient.addColorStop(.48, '#ff5aa5');
    sunGradient.addColorStop(1, '#d72cff');
    ctx.save();
    ctx.beginPath();
    ctx.arc(sunX, sunY, sunR, 0, Math.PI * 2);
    ctx.clip();
    ctx.fillStyle = sunGradient;
    ctx.fillRect(sunX - sunR, sunY - sunR, sunR * 2, sunR * 2);
    ctx.fillStyle = 'rgba(7,0,20,.72)';
    for (let y = sunY + 8; y < sunY + sunR; y += 14) {
      ctx.fillRect(sunX - sunR, y, sunR * 2, 5);
    }
    ctx.restore();

    // Blocky cabinet-era skyline.
    ctx.fillStyle = '#07000f';
    const block = Math.max(34, width / 28);
    for (let x = 0, i = 0; x < width + block; x += block, i++) {
      const h = 24 + ((i * 37) % 96);
      ctx.fillRect(x, horizon - h, block + 2, h + 3);
      ctx.fillStyle = i % 3 === 0 ? '#ff3cac' : '#00e5ff';
      ctx.globalAlpha = .32;
      for (let wy = horizon - h + 12; wy < horizon - 8; wy += 17) {
        ctx.fillRect(x + 9, wy, 3, 3);
      }
      ctx.globalAlpha = 1;
      ctx.fillStyle = '#07000f';
    }

    // Bright horizon line.
    ctx.shadowBlur = 14;
    ctx.shadowColor = 'rgba(255,60,172,.65)';
    ctx.strokeStyle = 'rgba(255,60,172,.9)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, horizon);
    ctx.lineTo(width, horizon);
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Perspective floor: fixed geometry with a subtle forward scroll.
    const centerX = width / 2;
    const floorBottom = height + 30;
    ctx.lineWidth = 1.4;
    for (let i = -12; i <= 12; i++) {
      const bottomX = centerX + i * (width / 11);
      ctx.strokeStyle = i % 2 === 0 ? 'rgba(0,229,255,.62)' : 'rgba(255,60,172,.6)';
      ctx.beginPath();
      ctx.moveTo(centerX, horizon);
      ctx.lineTo(bottomX, floorBottom);
      ctx.stroke();
    }

    const scroll = (time * .18) % 1;
    for (let i = 0; i < 14; i++) {
      const t = ((i + scroll) / 14);
      const eased = t * t;
      const y = horizon + eased * (height - horizon + 30);
      const alpha = .25 + eased * .65;
      ctx.strokeStyle = `rgba(255,60,172,${alpha})`;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }
  }

  function frame(ts) {
    if (!activeEffect || !ctx) return;
    const fps = activeEffect === 'cyber' ? 24 : 18;
    const interval = 1000 / fps;
    if (ts - lastFrame >= interval) {
      const dt = Math.min(.08, Math.max(.001, (ts - lastFrame) / 1000 || .016));
      lastFrame = ts;
      const t = ts / 1000;
      if (activeEffect === 'cyber') drawMatrix(dt);
      else if (activeEffect === 'midnight') drawStars(t);
      else if (activeEffect === 'princess') drawSparkles(t);
      else if (activeEffect === 'arcade') drawArcade(t);
    }
    if (!prefersReducedMotion()) raf = requestAnimationFrame(frame);
  }

  function sync() {
    const effect = document.documentElement.dataset.orangeEffect || 'classic';
    const supportsCanvas = ['cyber', 'midnight', 'princess', 'arcade'].includes(effect);
    const next = supportsCanvas ? effect : null;
    if (next === activeEffect) return;
    if (raf) cancelAnimationFrame(raf);
    raf = null;
    activeEffect = next;
    lastFrame = 0;
    ctx.clearRect(0, 0, width, height);
    if (!activeEffect) return;
    seedForEffect(activeEffect);
    if (prefersReducedMotion()) {
      if (activeEffect === 'midnight') drawStars(0);
      else if (activeEffect === 'princess') drawSparkles(2.4);
      else if (activeEffect === 'arcade') drawArcade(0);
      else drawMatrix(.016);
      return;
    }
    raf = requestAnimationFrame(frame);
  }

  window.addEventListener('orange:personalization-applied', sync);
  window.addEventListener('resize', resize, { passive: true });
  resize();
  sync();
})();
