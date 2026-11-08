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
    const curve = demo.querySelector('[data-curve]');
    const receiver = demo.querySelector('[data-receiver]');
    const speedInput = demo.querySelector('[data-speed]');
    const distanceInput = demo.querySelector('[data-distance]');
    const circles = Array.from({ length: 12 }, () => {
      const circle = document.createElementNS(svgNS, 'circle');
      circle.setAttribute('cy', '105');
      return circle;
    });
    waves.replaceChildren(...circles);
    // Educational display geometry. The scale preserves the physical v/c ratio.
    const soundSpeed = 70, scale = soundSpeed / 343;
    let speed = Number(speedInput.value) * scale;
    let distance = Number(distanceInput.value) * scale;
    let progress = 0.16, playing = !reducedMotion.matches, visible = false;
    let frame = null, previous = null;
    function frequencyAt(t) {
      // Exact subsonic solution of t = tau + hypot(v*tau, distance)/c.
      const a = soundSpeed ** 2 - speed ** 2;
      const tau = (soundSpeed ** 2 * t - Math.sqrt(soundSpeed ** 2 * speed ** 2 * t ** 2 + a * distance ** 2)) / a;
      const radial = speed ** 2 * tau / Math.hypot(speed * tau, distance);
      return soundSpeed / (soundSpeed + radial);
    }
    function chartY(ratio) { return 405 - (ratio - 1) * 90; }
    function updateParameters() {
      speed = Number(speedInput.value) * scale;
      distance = Number(distanceInput.value) * scale;
      demo.querySelector('[data-speed-value]').textContent = `${speedInput.value} m/s`;
      demo.querySelector('[data-distance-value]').textContent = `${distanceInput.value} m`;
      speedInput.setAttribute('aria-valuetext', `${speedInput.value} meters per second`);
      distanceInput.setAttribute('aria-valuetext', `${distanceInput.value} meters`);
      const points = Array.from({ length: 201 }, (_, i) => {
        const t = -14 + 28 * i / 200;
        return `${i ? 'L' : 'M'}${80 + 920 * i / 200},${chartY(frequencyAt(t))}`;
      });
      curve.setAttribute('d', points.join(' '));
      draw();
    }
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
      const ratio = frequencyAt(t);
      // This connector shows present aircraft-to-microphone geometry.
      line.setAttribute('d', `M${x} 105L540 ${105 + distance}`);
      receiver.setAttribute('transform', `translate(0 ${distance - 160})`);
      const chartX = 80 + progress * 920;
      dot.setAttribute('cx', chartX);
      dot.setAttribute('cy', chartY(ratio));
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
    speedInput.addEventListener('input', updateParameters);
    distanceInput.addEventListener('input', updateParameters);
    let dragPointer = null;
    function moveMicrophone(event) {
      const point = scene.createSVGPoint();
      point.x = event.clientX;
      point.y = event.clientY;
      const position = point.matrixTransform(scene.getScreenCTM().inverse());
      distanceInput.value = Math.max(250, Math.min(850, Math.round((position.y - 105) / scale / 10) * 10));
      updateParameters();
    }
    receiver.addEventListener('pointerdown', event => {
      if (event.button !== 0 || dragPointer !== null) return;
      event.preventDefault();
      playing = false;
      previous = null;
      updateButton();
      dragPointer = event.pointerId;
      receiver.setPointerCapture(event.pointerId);
      moveMicrophone(event);
    });
    receiver.addEventListener('pointermove', event => {
      if (event.pointerId === dragPointer) moveMicrophone(event);
    });
    receiver.addEventListener('pointerup', event => {
      if (event.pointerId === dragPointer) receiver.releasePointerCapture(event.pointerId);
    });
    receiver.addEventListener('lostpointercapture', () => { dragPointer = null; });
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
    updateParameters();
  });

  // The scroll sequence also offers native keyboard navigation. Only the
  // currently displayed diagram is focusable; static layouts retain every link.
  const method = document.querySelector('[data-moment="pinned-chapters"]');
  if (method) {
    const stages = Array.from(method.querySelectorAll('.mo-pc__step')).map((step, index) => {
      const heading = step.querySelector('h3');
      const label = heading.textContent;
      const figure = Array.from(method.querySelectorAll('.mo-pc__visual')).find(item => item.getAttribute('aria-labelledby') === heading.id);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'method-step';
      button.textContent = label;
      button.addEventListener('click', () => {
        const start = window.scrollY + method.getBoundingClientRect().top;
        const travel = Math.max(0, method.offsetHeight - window.innerHeight);
        window.scrollTo({ top: start + travel * (index + 0.5) / stages.length, behavior: 'instant' });
      });
      return { step, heading, label, figure, button };
    });
    function syncMethod() {
      const live = method.classList.contains('is-live');
      stages.forEach(({ step, heading, label, figure, button }) => {
        const active = step.classList.contains('is-on');
        if (figure) figure.inert = live && !active;
        if (live) {
          if (heading.firstChild !== button) heading.replaceChildren(button);
          button.setAttribute('aria-pressed', String(active));
        } else if (heading.firstChild === button) {
          const hadFocus = document.activeElement === button;
          heading.textContent = label;
          if (hadFocus && figure) figure.querySelector('a')?.focus({ preventScroll: true });
        }
      });
    }
    new MutationObserver(syncMethod).observe(method, { attributes: true, attributeFilter: ['class'], subtree: true });
    syncMethod();
  }

  if (typeof HTMLDialogElement === 'undefined') return;
  const viewer = document.createElement('dialog');
  viewer.className = 'figure-viewer';
  viewer.setAttribute('aria-labelledby', 'viewer-title');
  viewer.innerHTML = '<div class="viewer-toolbar"><p id="viewer-title"></p><button type="button" class="viewer-close" autofocus>Close <span aria-hidden="true">×</span></button></div><p class="viewer-status" role="status" hidden></p><img alt="" width="2610" height="1278"><p class="viewer-caption"></p><a class="viewer-original">Open original image ↗</a>';
  document.body.append(viewer);
  const fullImage = viewer.querySelector('img');
  const imageStatus = viewer.querySelector('.viewer-status');
  fullImage.addEventListener('load', () => {
    viewer.removeAttribute('aria-busy');
    imageStatus.hidden = true;
  });
  fullImage.addEventListener('error', () => {
    viewer.removeAttribute('aria-busy');
    fullImage.hidden = true;
    imageStatus.hidden = false;
    imageStatus.textContent = 'The full-size figure could not load. Try opening the original image below.';
  });
  viewer.querySelector('button').addEventListener('click', () => viewer.close());
  viewer.addEventListener('click', event => { if (event.target === viewer) viewer.close(); });
  document.querySelectorAll('.figure-link').forEach(link => {
    link.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      const figure = link.closest('figure');
      const heading = figure.querySelector('.figure-heading span') || document.getElementById(figure.getAttribute('aria-labelledby'));
      viewer.querySelector('#viewer-title').textContent = heading ? heading.textContent : 'Research figure';
      const image = viewer.querySelector('img');
      const preview = link.querySelector('img');
      image.width = Number(preview.getAttribute('width'));
      image.height = Number(preview.getAttribute('height'));
      image.hidden = false;
      imageStatus.textContent = 'Loading full-size figure…';
      imageStatus.hidden = false;
      viewer.setAttribute('aria-busy', 'true');
      image.src = link.href;
      image.alt = preview.alt;
      const description = figure.querySelector('figcaption') || document.getElementById(figure.getAttribute('aria-describedby'));
      viewer.querySelector('.viewer-caption').textContent = description ? description.textContent : preview.alt;
      viewer.querySelector('.viewer-original').href = link.href;
      viewer.showModal();
    });
  });
})();
