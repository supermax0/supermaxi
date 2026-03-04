// Helper to load GLTFLoader
(function() {
  if (typeof THREE === 'undefined') {
    console.error('Three.js must be loaded first');
    return;
  }
  
  if (typeof THREE.GLTFLoader !== 'undefined') {
    return; // Already loaded
  }
  
  // Try to load from CDN
  const script = document.createElement('script');
  script.src = 'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/GLTFLoader.js';
  script.async = true;
  
  script.onload = function() {
    console.log('✅ GLTFLoader loaded successfully');
  };
  
  script.onerror = function() {
    console.error('❌ Failed to load GLTFLoader');
    // Fallback: try alternative CDN
    const altScript = document.createElement('script');
    altScript.src = 'https://unpkg.com/three@0.128.0/examples/js/loaders/GLTFLoader.js';
    document.head.appendChild(altScript);
  };
  
  document.head.appendChild(script);
})();
