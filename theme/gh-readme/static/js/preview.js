let mermaidId = 0;
let mermaidVersionPromise;
const copyResetDelay = 2000;

function copyIcon() {
  return `
    <svg aria-hidden="true" height="16" viewBox="0 0 16 16" width="16" class="ghrm-copy-icon ghrm-copy-icon-copy">
      <path d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 9.25 16h-7.5A1.75 1.75 0 0 1 0 14.25Z"></path>
      <path d="M5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 .784 16 1.75v7.5A1.75 1.75 0 0 1 14.25 11h-7.5A1.75 1.75 0 0 1 5 9.25Zm1.75-.25a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25Z"></path>
    </svg>
  `;
}

function checkIcon() {
  return `
    <svg aria-hidden="true" height="16" viewBox="0 0 16 16" width="16" class="ghrm-copy-icon ghrm-copy-icon-check">
      <path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.751.751 0 0 1 .018-1.042.751.751 0 0 1 1.042-.018L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z"></path>
    </svg>
  `;
}

function getCopyHost(pre) {
  const wrapper = pre.parentElement;
  if (wrapper?.classList.contains('highlight')) {
    return wrapper;
  }

  return pre;
}

function getCopyText(pre) {
  return pre.querySelector('code')?.textContent || pre.textContent || '';
}

async function writeClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const input = document.createElement('textarea');
  input.value = text;
  input.setAttribute('readonly', '');
  input.style.position = 'absolute';
  input.style.left = '-9999px';
  document.body.appendChild(input);
  input.select();
  document.execCommand('copy');
  input.remove();
}

function showCopied(button) {
  if (button._ghrmCopyReset) {
    window.clearTimeout(button._ghrmCopyReset);
  }

  button.classList.add('is-copied');
  button.setAttribute('aria-label', 'Copied!');

  button._ghrmCopyReset = window.setTimeout(() => {
    button.classList.remove('is-copied');
    button.setAttribute('aria-label', 'Copy');
    button._ghrmCopyReset = null;
  }, copyResetDelay);
}

function addCopyButtons() {
  for (const pre of document.querySelectorAll('.markdown-body pre')) {
    const host = getCopyHost(pre);
    if (!host || host.querySelector(':scope > .ghrm-copy-button')) {
      continue;
    }

    host.classList.add('ghrm-copy-host');
    pre.classList.add('ghrm-copy-target');

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'ghrm-copy-button';
    button.setAttribute('aria-label', 'Copy');
    button.dataset.copyFeedback = 'Copied!';
    button.innerHTML = `${copyIcon()}${checkIcon()}`;
    button.addEventListener('click', async () => {
      await writeClipboard(getCopyText(pre));
      showCopied(button);
    });

    host.appendChild(button);
  }
}

function getSource(block) {
  return block.querySelector('.ghrm-data')?.content?.textContent?.trim() || '';
}

function isDarkTheme() {
  return document.documentElement.getAttribute('data-theme') === 'dark';
}

function setError(block, message) {
  let node = block.querySelector('.ghrm-error');
  if (!node) {
    node = document.createElement('p');
    node.className = 'ghrm-error';
    block.appendChild(node);
  }
  node.hidden = false;
  node.textContent = message;
}

function clearError(block) {
  const node = block.querySelector('.ghrm-error');
  if (node) {
    node.hidden = true;
    node.textContent = '';
  }
}

function themeColors() {
  return {
    polygon: '#6f42c1',
    polygonFill: '#6f42c1',
    line: '#0969da',
    point: '#0969da',
  };
}

function restoreGitHubInlineMath(container) {
  for (const code of container.querySelectorAll('code')) {
    if (code.closest('pre')) {
      continue;
    }

    const previous = code.previousSibling;
    const next = code.nextSibling;
    if (previous?.nodeType !== Node.TEXT_NODE || next?.nodeType !== Node.TEXT_NODE) {
      continue;
    }

    const before = previous.textContent || '';
    const after = next.textContent || '';
    if (!before.endsWith('$') || !after.startsWith('$')) {
      continue;
    }

    const math = document.createTextNode(
      `${before.slice(0, -1)}$${code.textContent || ''}$${after.slice(1)}`
    );
    code.replaceWith(math);
    previous.textContent = before.slice(0, -1);
    next.textContent = after.slice(1);
    previous.remove();
    next.remove();
  }
}

function renderMath() {
  if (typeof window.renderMathInElement !== 'function') {
    return;
  }

  for (const container of document.querySelectorAll('.markdown-body')) {
    // GitHub's $`...`$ form becomes $<code>...</code>$ after Markdown parsing.
    restoreGitHubInlineMath(container);
    window.renderMathInElement(container, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '$`', right: '`$', display: false },
        { left: '$', right: '$', display: false },
        { left: '\\(', right: '\\)', display: false },
        { left: '\\[', right: '\\]', display: true },
      ],
      throwOnError: false,
      ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
    });
  }
}

async function renderMermaid() {
  const api = window.mermaid;
  const blocks = document.querySelectorAll('.ghrm-mermaid');
  if (!api || blocks.length === 0) {
    return;
  }

  api.initialize({
    startOnLoad: false,
    theme: 'neutral',
    themeVariables: {
      primaryColor: '#eae4f5',
      primaryBorderColor: '#998eb5',
      primaryTextColor: '#1f2328',
      lineColor: '#666',
      secondaryColor: '#eae4f5',
      tertiaryColor: '#eae4f5',
    },
  });

  for (const block of blocks) {
    const source = getSource(block);
    const target = block.querySelector('.ghrm-mermaid-diagram');
    if (!source || !target) {
      continue;
    }

    clearError(block);
    target.innerHTML = '';

    try {
      if (source.trim() === 'info') {
        const version = await getMermaidVersion(api);
        target.innerHTML = `<pre class="ghrm-mermaid-info">mermaid ${version}</pre>`;
        continue;
      }

      const result = await api.render(`ghrm-mermaid-${mermaidId++}`, source);
      target.innerHTML = result.svg;
      if (typeof result.bindFunctions === 'function') {
        result.bindFunctions(target);
      }
    } catch (error) {
      setError(block, error.message);
    }
  }
}

async function getMermaidVersion(api) {
  if (typeof api.version === 'function') {
    return api.version();
  }

  if (api.version) {
    return api.version;
  }

  if (!mermaidVersionPromise) {
    mermaidVersionPromise = fetch('/vendor/mermaid-version.txt')
      .then((r) => r.text())
      .then((t) => t.trim() || 'unknown')
      .catch(() => 'unknown');
  }

  return mermaidVersionPromise;
}

function topojsonToGeojson(data) {
  const objects = Object.values(data.objects || {});
  const features = [];

  for (const object of objects) {
    const value = window.topojson.feature(data, object);
    if (value.type === 'FeatureCollection') {
      features.push(...value.features);
    } else {
      features.push(value);
    }
  }

  return {
    type: 'FeatureCollection',
    features,
  };
}

function renderMapBlock(block, kind) {
  if (block._ghrmMap) {
    block._ghrmMap.remove();
    block._ghrmMap = null;
  }

  const previous = block.querySelector('.ghrm-map-canvas');
  const canvas = previous.cloneNode(false);
  previous.replaceWith(canvas);

  const source = getSource(block);
  if (!source) {
    return;
  }

  const data = JSON.parse(source);
  const geojson = kind === 'topojson' ? topojsonToGeojson(data) : data;
  const colors = themeColors();
  const map = window.L.map(canvas, {
    attributionControl: false,
    zoomControl: true,
    scrollWheelZoom: true,
  });

  window.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
  }).addTo(map);

  const layer = window.L.geoJSON(geojson, {
    style(feature) {
      const type = feature?.geometry?.type || '';
      if (type === 'Point' || type === 'MultiPoint') {
        return { color: colors.point, weight: 2 };
      }
      if (type.includes('Line')) {
        return { color: colors.line, weight: 3, opacity: 1 };
      }
      return {
        color: colors.polygon,
        fillColor: colors.polygonFill,
        fillOpacity: 0.3,
        opacity: 0.8,
        weight: 2,
      };
    },
    pointToLayer(_feature, latlng) {
      return window.L.circleMarker(latlng, {
        color: colors.point,
        fillColor: colors.point,
        fillOpacity: 0.9,
        radius: 6,
        weight: 1,
      });
    },
  }).addTo(map);

  const bounds = layer.getBounds();
  if (bounds.isValid()) {
    map.fitBounds(bounds.pad(0.1));
  } else {
    map.setView([0, 0], 1);
  }

  block._ghrmMap = map;
}

function renderMaps() {
  if (!window.L) {
    return;
  }

  for (const [selector, kind] of [['.ghrm-geojson', 'geojson'], ['.ghrm-topojson', 'topojson']]) {
    for (const block of document.querySelectorAll(selector)) {
      clearError(block);
      try {
        renderMapBlock(block, kind);
      } catch (error) {
        setError(block, error.message);
      }
    }
  }
}

async function renderStlBlock(block) {
  const canvas = block.querySelector('.ghrm-stl-canvas');
  const source = getSource(block);
  if (!canvas || !source) {
    return;
  }

  const THREE = await import('three');
  const { OrbitControls } = await import('/vendor/three/OrbitControls.js');
  const { STLLoader } = await import('/vendor/three/STLLoader.js');

  if (block._ghrmStl) {
    block._ghrmStl.observer.disconnect();
    block._ghrmStl.controls.dispose();
    block._ghrmStl.renderer.dispose();
    block._ghrmStl = null;
  }

  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    canvas,
  });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = false;

  const material = new THREE.MeshPhongMaterial({
    color: 0x0969da,
    shininess: 10,
    specular: new THREE.Color(0x444444),
  });

  const geometry = new STLLoader().parse(source);
  geometry.computeVertexNormals();
  geometry.center();

  const mesh = new THREE.Mesh(geometry, material);
  scene.add(mesh);

  scene.add(new THREE.AmbientLight(0xffffff, 1.0));

  const main = new THREE.DirectionalLight(0xffffff, 0.8);
  main.position.set(1, 2, 1.5);
  scene.add(main);

  const fill = new THREE.DirectionalLight(0xffffff, 0.4);
  fill.position.set(-1, -0.5, 1);
  scene.add(fill);

  // Fit the camera from the model's bounding box so arbitrary STL files land in frame.
  const box = new THREE.Box3().setFromObject(mesh);
  const size = box.getSize(new THREE.Vector3());
  const maxDimension = Math.max(size.x, size.y, size.z) || 1;
  const distance = maxDimension * 2.5;

  const grid = new THREE.GridHelper(maxDimension * 4, 12, 0x000000, 0x000000);
  grid.position.y = -size.y / 2;
  scene.add(grid);

  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(geometry),
    new THREE.LineBasicMaterial({ color: 0x57606a })
  );
  edges.visible = false;
  scene.add(edges);

  camera.position.set(distance, distance * 0.85, distance);
  camera.lookAt(0, 0, 0);
  controls.target.set(0, 0, 0);
  controls.update();

  const buttons = block.querySelectorAll('.ghrm-stl-button');
  const setMode = (mode) => {
    for (const button of buttons) {
      button.classList.toggle('is-active', button.dataset.mode === mode);
    }

    if (mode === 'wireframe') {
      material.wireframe = true;
      material.flatShading = false;
      edges.visible = false;
    } else if (mode === 'surface-angle') {
      material.wireframe = false;
      material.flatShading = true;
      edges.visible = true;
    } else {
      material.wireframe = false;
      material.flatShading = false;
      edges.visible = false;
    }

    material.needsUpdate = true;
    render();
  };

  for (const button of buttons) {
    button.onclick = () => setMode(button.dataset.mode || 'solid');
  }

  const render = () => {
    controls.update();
    renderer.render(scene, camera);
  };

  const resize = () => {
    const width = canvas.clientWidth || canvas.parentElement.clientWidth || 640;
    const height = canvas.clientHeight || 420;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height, false);
    render();
  };

  controls.addEventListener('change', render);

  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  resize();
  setMode('solid');

  block._ghrmStl = {
    controls,
    material,
    observer,
    renderer,
    render,
  };
}

async function renderStl() {
  const blocks = document.querySelectorAll('.ghrm-stl');
  if (blocks.length === 0) {
    return;
  }

  for (const block of blocks) {
    clearError(block);
    try {
      await renderStlBlock(block);
    } catch (error) {
      setError(block, error.message);
    }
  }
}

function refreshStlTheme() {
  for (const block of document.querySelectorAll('.ghrm-stl')) {
    if (!block._ghrmStl) {
      continue;
    }

    block._ghrmStl.material.color.set(0x0969da);
    block._ghrmStl.render();
  }
}

document.addEventListener('DOMContentLoaded', async function() {
  renderMath();
  await renderMermaid();
  renderMaps();
  await renderStl();
  addCopyButtons();
});

document.addEventListener('ghrm:themechange', async function() {
  await renderMermaid();
  renderMaps();
  refreshStlTheme();
  addCopyButtons();
});
