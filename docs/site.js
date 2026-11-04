/* Progressive enhancement only: content, diagrams and original image links work without JS. */
(() => {
  'use strict';
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const svgNS = 'http://www.w3.org/2000/svg';

  document.querySelectorAll('[data-doppler]').forEach(demo => {
    const scene = demo.querySelector('svg');
    const waves = demo.querySelector('[data-waves]');
    const plane = demo.querySelector('[data-plane]');
    const line = demo.querySelector('[data-sound-link]');
    const dot = demo.querySelector('[data-dot]');
    const cursor = demo.querySelector('[data-cursor]');
    const slider = demo.querySelector('[data-time]');
    const play = demo.querySelector('[data-play]');
    const phase = demo.querySelector('[data-phase]');
    const pitch = demo.querySelector('[data-pitch]');
    const circles = Array.from({ length: 12 }, () => {
      const circle = document.createElementNS(svgNS, 'circle');
      circle.setAttribute('cy', '105');
      return circle;
    });
    waves.replaceChildren(...circles);
    // Display units, not measured data. v/c = 25/70; microphone is 160 units off track.
    const speed = 25, soundSpeed = 70, distance = 160;
    let progress = 0.16, playing = !reducedMotion.matches, visible = false;
    let frame = null, previous = null;
    function draw() {
      const t = -14 + 28 * progress;
      const x = 540 + speed * t;
      plane.setAttribute('transform', `translate(${x} 105)`);
      const latestEmission = Math.floor(t / 0.8) * 0.8;
      circles.forEach((circle, i) => {
        const emitted = latestEmission - i * 0.8;
        circle.setAttribute('cx', 540 + speed * emitted);
        circle.setAttribute('r', (t - emitted) * soundSpeed);
      });
      // Invert t = tau + r(tau)/c. Frequency depends on velocity at emission.
      let low = t - 30, high = t;
      for (let i = 0; i < 40; i++) {
        const tau = (low + high) / 2;
        if (tau + Math.hypot(speed * tau, distance) / soundSpeed < t) low = tau;
        else high = tau;
      }
      const tau = (low + high) / 2;
      const radial = speed * speed * tau / Math.hypot(speed * tau, distance);
      const ratio = soundSpeed / (soundSpeed + radial);
      // Dashed line connects the emission position, rather than the current plane, to the receiver.
      line.setAttribute('d', `M${540 + speed * tau} 105L540 265`);
      const chartX = 80 + progress * 920;
      dot.setAttribute('cx', chartX);
      dot.setAttribute('cy', 405 - (ratio - 1) * 130);
      cursor.setAttribute('d', `M${chartX} 340V456`);
      const label = Math.abs(ratio - 1) < 0.02 ? 'Near source pitch' : ratio > 1 ? 'Approaching · higher pitch' : 'Receding · lower pitch';
      phase.textContent = label;
      pitch.textContent = `${ratio.toFixed(2)}× source pitch`;
      slider.value = Math.round(progress * 1000);
      slider.setAttribute('aria-valuetext', `${Math.round(progress * 100)}% through flyover, ${label.toLowerCase()}, ${ratio.toFixed(2)} times source pitch`);
      // Keep frequent animation updates out of screen-reader live regions.
      pitch.setAttribute('aria-live', 'off');
    }
    function updateButton() {
      play.textContent = playing ? 'Pause flyover' : progress >= 1 ? 'Replay flyover' : 'Play flyover';
    }
    function tick(now) {
      frame = null;
      if (!playing || !visible || document.hidden) { previous = null; return; }
      if (previous !== null) progress = Math.min(1, progress + Math.min(now - previous, 100) / 18000);
      previous = now;
      draw();
      if (progress >= 1) { playing = false; previous = null; updateButton(); }
      else frame = requestAnimationFrame(tick);
    }
    function schedule() {
      if (playing && visible && !document.hidden && frame === null) frame = requestAnimationFrame(tick);
    }
    play.addEventListener('click', () => {
      if (progress >= 1) progress = 0;
      playing = !playing;
      previous = null;
      updateButton();
      schedule();
    });
    slider.addEventListener('input', () => {
      playing = false;
      previous = null;
      progress = Number(slider.value) / 1000;
      updateButton();
      draw();
    });
    reducedMotion.addEventListener('change', () => {
      if (reducedMotion.matches) { playing = false; previous = null; updateButton(); }
    });
    document.addEventListener('visibilitychange', () => { previous = null; schedule(); });
    const observer = new IntersectionObserver(entries => {
      visible = entries[0].isIntersecting;
      previous = null;
      schedule();
    }, { threshold: 0.15 });
    observer.observe(scene);
    demo.querySelector('.demo-controls').hidden = false;
    updateButton();
    draw();
  });

  if (typeof HTMLDialogElement === 'undefined') return;
  const viewer = document.createElement('dialog');
  viewer.className = 'figure-viewer';
  viewer.setAttribute('aria-labelledby', 'viewer-title');
  viewer.innerHTML = '<div class="viewer-toolbar"><p id="viewer-title"></p><button type="button" class="viewer-close" autofocus>Close <span aria-hidden="true">×</span></button></div><img alt=""><p class="viewer-caption"></p><a class="viewer-original">Open original image ↗</a>';
  document.body.append(viewer);
  viewer.querySelector('button').addEventListener('click', () => viewer.close());
  viewer.addEventListener('click', event => { if (event.target === viewer) viewer.close(); });
  document.querySelectorAll('.figure-link').forEach(link => {
    link.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      const figure = link.closest('figure');
      viewer.querySelector('#viewer-title').textContent = figure.querySelector('.figure-heading span').textContent;
      const image = viewer.querySelector('img');
      image.src = link.href;
      image.alt = link.querySelector('img').alt;
      viewer.querySelector('.viewer-caption').textContent = figure.querySelector('figcaption').textContent;
      viewer.querySelector('.viewer-original').href = link.href;
      viewer.showModal();
    });
  });
})();
