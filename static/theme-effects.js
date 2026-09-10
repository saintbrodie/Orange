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
    const spacing = 24;
    const count = Math.ceil(width / spacing);
    matrixColumns = Array.from({ length: count }, (_, i) => ({
      x: i * spacing + Math.random() * 8,
      y: -Math.random() * height,
      speed: 34 + Math.random() * 72,
      length: 8 + Math.floor(Math.random() * 18),
      glyphs: Array.from({ length: 28 }, randomGlyph),
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
    const count = Math.max(12, Math.min(26, Math.round((width * height) / 65000)));
    sparkles = Array.from({ length: count }, () => ({
      x: 24 + Math.random() * Math.max(1, width - 48),
      y: 24 + Math.random() * Math.max(1, height - 48),
      size: 1.5 + Math.random() * 3.5,
      phase: Math.random() * Math.PI * 2,
      speed: .16 + Math.random() * .28,
      drift: 2 + Math.random() * 7,
      pink: Math.random() < .45,
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
    ctx.fillStyle = 'rgba(1, 6, 3, 0.12)';
    ctx.fillRect(0, 0, width, height);
    ctx.font = '14px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    for (const col of matrixColumns) {
      col.y += col.speed * dt;
      col.mutation += dt * 1000;
      if (col.mutation > 110) {
        col.mutation = 0;
        const index = Math.floor(Math.random() * col.glyphs.length);
        col.glyphs[index] = randomGlyph();
      }

      for (let i = 0; i < col.length; i++) {
        const y = col.y - i * 19;
        if (y < -24 || y > height + 24) continue;
        const fade = 1 - i / col.length;
        if (i === 0) {
          ctx.shadowBlur = 11;
          ctx.shadowColor = 'rgba(190,255,211,.9)';
          ctx.fillStyle = 'rgba(225,255,234,.95)';
        } else {
          ctx.shadowBlur = i < 3 ? 6 : 0;
          ctx.shadowColor = 'rgba(57,255,136,.7)';
          ctx.fillStyle = `rgba(57,255,136,${Math.max(.025, fade * .48)})`;
        }
        ctx.fillText(col.glyphs[i % col.glyphs.length], col.x, y);
      }
      ctx.shadowBlur = 0;

      if (col.y - col.length * 19 > height + 40) {
        col.y = -40 - Math.random() * height * .65;
        col.speed = 34 + Math.random() * 72;
        col.length = 8 + Math.floor(Math.random() * 18);
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
      const alpha = Math.pow(wave, 3) * .72;
      if (alpha < .035) continue;
      const y = sparkle.y + Math.sin(time * .12 + sparkle.phase) * sparkle.drift;
      const color = sparkle.pink ? `rgba(219,63,141,${alpha})` : `rgba(255,246,251,${alpha})`;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.shadowBlur = 8;
      ctx.shadowColor = color;
      ctx.beginPath();
      ctx.moveTo(sparkle.x - sparkle.size * 2.2, y);
      ctx.lineTo(sparkle.x + sparkle.size * 2.2, y);
      ctx.moveTo(sparkle.x, y - sparkle.size * 2.2);
      ctx.lineTo(sparkle.x, y + sparkle.size * 2.2);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(sparkle.x, y, sparkle.size * .55, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
    }
    ctx.shadowBlur = 0;
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
    }
    if (!prefersReducedMotion()) raf = requestAnimationFrame(frame);
  }

  function sync() {
    const effect = document.documentElement.dataset.orangeEffect || 'classic';
    const supportsCanvas = ['cyber', 'midnight', 'princess'].includes(effect);
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
