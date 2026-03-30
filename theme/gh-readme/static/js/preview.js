let mermaidSerial = 0;
let mermaidVersionPromise;

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

  let index = 0;
  for (const block of blocks) {
    const source = getSource(block);
    const target = block.querySelector('.ghrm-mermaid-diagram');
    if (!source || !target) {
      index += 1;
      continue;
    }

    clearError(block);
    target.innerHTML = '';

    try {
      if (source.trim() === 'info') {
        const version = await getMermaidVersion(api);
        target.innerHTML = `<pre class="ghrm-mermaid-info">mermaid ${version}</pre>`;
        index += 1;
        continue;
      }

      const id = `ghrm-mermaid-${mermaidSerial}-${index}`;
      const result = await api.render(id, source);
      mermaidSerial += 1;
      target.innerHTML = result.svg;
      if (typeof result.bindFunctions === 'function') {
        result.bindFunctions(target);
      }
    } catch (error) {
      setError(block, error.message);
    }

    index += 1;
  }
}

async function getMermaidVersion(api) {
  const direct =
    (typeof api.version === 'function' && api.version()) ||
    api.version ||
    api.mermaidAPI?.version;
  if (direct) {
    return direct;
  }

  if (!mermaidVersionPromise) {
    mermaidVersionPromise = fetch('/vendor/mermaid-version.txt')
      .then((response) => response.text())
      .then((text) => text.trim() || 'unknown')
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

  for (const block of document.querySelectorAll('.ghrm-geojson')) {
    clearError(block);
    try {
      renderMapBlock(block, 'geojson');
    } catch (error) {
      setError(block, error.message);
    }
  }

  for (const block of document.querySelectorAll('.ghrm-topojson')) {
    clearError(block);
    try {
      renderMapBlock(block, 'topojson');
    } catch (error) {
      setError(block, error.message);
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
});

document.addEventListener('ghrm:themechange', async function() {
  await renderMermaid();
  renderMaps();
  refreshStlTheme();
});
