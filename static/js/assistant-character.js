// ============================================
// المساعد الذكي - شخصية 3D أنمي
// ============================================

class AssistantCharacter {
  constructor(containerId, options = {}) {
    this.container = document.getElementById(containerId);
    if (!this.container) return;
    
    this.options = {
      size: options.size || 'large', // large, small, mini
      position: options.position || 'bottom-right', // bottom-right, top-right, etc.
      autoAnalyze: options.autoAnalyze !== false,
      voiceEnabled: options.voiceEnabled !== false,
      ...options
    };
    
    this.scene = null;
    this.camera = null;
    this.renderer = null;
    this.character = null;
    this.isSpeaking = false;
    this.voiceEnabled = this.options.voiceEnabled;
    this.currentMood = 'neutral';
    this.animationId = null;
    this.issues = [];
    
    this.init();
  }
  
  init() {
    this.createCanvas();
    this.setupScene();
    this.loadGLBModel();
    this.animate();
    this.setupInteractions();
    
    if (this.options.autoAnalyze) {
      this.startAutoAnalysis();
    }
  }
  
  createCanvas() {
    const canvas = document.createElement('canvas');
    canvas.id = 'assistant-canvas-' + this.options.size;
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.display = 'block';
    this.container.appendChild(canvas);
    this.canvas = canvas;
  }
  
  setupScene() {
    // Scene
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0a0f1c);
    this.scene.fog = new THREE.Fog(0x0a0f1c, 10, 50);
    
    // Camera
    const aspect = this.container.clientWidth / this.container.clientHeight;
    this.camera = new THREE.PerspectiveCamera(50, aspect, 0.1, 1000);
    
    if (this.options.size === 'mini') {
      this.camera.position.set(0, 1.2, 2.5);
    } else if (this.options.size === 'small') {
      this.camera.position.set(0, 1.3, 3);
    } else {
      this.camera.position.set(0, 1.5, 3);
    }
    
    // Renderer
    this.renderer = new THREE.WebGLRenderer({ 
      canvas: this.canvas,
      antialias: true,
      alpha: true
    });
    this.renderer.setSize(this.container.clientWidth, this.container.clientHeight);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    
    // Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    this.scene.add(ambientLight);
    
    // Main light (من العيون) - محسّن
    const eyeLight = new THREE.PointLight(0xff6b35, 2.0, 12);
    eyeLight.position.set(0, 1.5, 0.3);
    eyeLight.castShadow = true;
    this.scene.add(eyeLight);
    this.eyeLight = eyeLight;
    
    // Hair glow - محسّن
    const hairLight = new THREE.PointLight(0xff4444, 1.2, 10);
    hairLight.position.set(0, 1.8, 0);
    this.scene.add(hairLight);
    this.hairLight = hairLight;
    
    // Halo glow
    const haloLight = new THREE.PointLight(0x8b5cf6, 0.8, 8);
    haloLight.position.set(0, 1.95, 0);
    this.scene.add(haloLight);
    this.haloLight = haloLight;
    
    // Rim light محسّن
    const rimLight2 = new THREE.DirectionalLight(0xff6b35, 0.2);
    rimLight2.position.set(0, 5, -5);
    this.scene.add(rimLight2);
    
    // Directional light
    const dirLight = new THREE.DirectionalLight(0xffffff, 0.6);
    dirLight.position.set(5, 10, 5);
    dirLight.castShadow = true;
    this.scene.add(dirLight);
    
    // Rim light
    const rimLight = new THREE.DirectionalLight(0x8b5cf6, 0.3);
    rimLight.position.set(-5, 5, -5);
    this.scene.add(rimLight);
    
    // خلفية سحرية (جزيئات)
    this.createParticleBackground();
  }
  
  createParticleBackground() {
    const particleGroup = new THREE.Group();
    const particleCount = 50;
    
    for (let i = 0; i < particleCount; i++) {
      const particleGeometry = new THREE.SphereGeometry(0.01, 8, 8);
      const particleMaterial = new THREE.MeshStandardMaterial({ 
        color: 0x8b5cf6,
        emissive: 0x8b5cf6,
        emissiveIntensity: 1.5,
        transparent: true,
        opacity: 0.6
      });
      const particle = new THREE.Mesh(particleGeometry, particleMaterial);
      
      particle.position.set(
        (Math.random() - 0.5) * 10,
        (Math.random() - 0.5) * 10,
        (Math.random() - 0.5) * 10 - 5
      );
      
      particle.userData = {
        speed: Math.random() * 0.02 + 0.01,
        rotationSpeed: Math.random() * 0.05 + 0.02
      };
      
      particleGroup.add(particle);
    }
    
    this.scene.add(particleGroup);
    this.particleGroup = particleGroup;
  }
  
  loadGLBModel() {
    // تحميل النموذج 3D من ملف GLB
    // التحقق من وجود GLTFLoader
    if (typeof THREE === 'undefined' || typeof THREE.GLTFLoader === 'undefined') {
      console.warn('GLTFLoader غير متوفر. سيتم استخدام شخصية بديلة.');
      setTimeout(() => {
        if (typeof THREE !== 'undefined' && typeof THREE.GLTFLoader !== 'undefined') {
          this.loadGLBModel();
        } else {
          this.createFallbackCharacter();
        }
      }, 500);
      return;
    }
    
    const loader = new THREE.GLTFLoader();
    
    loader.load(
      '/static/assistant.glb',
      (gltf) => {
        // النموذج تم تحميله بنجاح
        this.character = gltf.scene;
        
        // تكبير/تصغير حسب الحجم
        if (this.options.size === 'mini') {
          this.character.scale.set(0.8, 0.8, 0.8);
        } else if (this.options.size === 'small') {
          this.character.scale.set(1.0, 1.0, 1.0);
        } else {
          this.character.scale.set(1.2, 1.2, 1.2);
        }
        
        // إضافة الظلال
        this.character.traverse((child) => {
          if (child.isMesh) {
            child.castShadow = true;
            child.receiveShadow = true;
            
            // تحسين المواد
            if (child.material) {
              if (Array.isArray(child.material)) {
                child.material.forEach(mat => {
                  if (mat) {
                    mat.needsUpdate = true;
                  }
                });
              } else {
                child.material.needsUpdate = true;
              }
            }
          }
        });
        
        // إضافة النموذج إلى المشهد
        this.scene.add(this.character);
        
        // البحث عن أجزاء محددة للتحكم بها
        this.findCharacterParts();
        
        // إضافة إضاءة إضافية للنموذج
        this.addModelLighting();
        
        // تحريك النموذج
        this.setupModelAnimations(gltf);
        
        // تحديث الكاميرا للنموذج
        this.centerModel();
        
        console.log('✅ تم تحميل النموذج بنجاح');
      },
      (progress) => {
        // أثناء التحميل
        const percent = (progress.loaded / progress.total) * 100;
        console.log(`جاري التحميل: ${percent.toFixed(0)}%`);
      },
      (error) => {
        console.error('❌ خطأ في تحميل النموذج:', error);
        // في حالة الخطأ، إنشاء شخصية بسيطة كبديل
        this.createFallbackCharacter();
      }
    );
  }
  
  findCharacterParts() {
    if (!this.character) return;
    
    // البحث عن أجزاء محددة في النموذج
    this.character.traverse((child) => {
      if (child.isMesh) {
        const name = child.name.toLowerCase();
        
        // العيون
        if (name.includes('eye') || name.includes('عين')) {
          if (!this.eyeGroup) this.eyeGroup = new THREE.Group();
          this.eyeGroup.add(child);
        }
        
        // الفم
        if (name.includes('mouth') || name.includes('فم')) {
          this.mouth = child;
        }
        
        // الشعر
        if (name.includes('hair') || name.includes('شعر')) {
          if (!this.hairGroup) this.hairGroup = new THREE.Group();
          this.hairGroup.add(child);
        }
        
        // الرأس
        if (name.includes('head') || name.includes('رأس')) {
          this.head = child;
        }
        
        // الأذرع
        if (name.includes('arm') || name.includes('ذراع')) {
          if (!this.arms) this.arms = [];
          this.arms.push(child);
        }
      }
    });
    
    // إذا لم نجد أجزاء محددة، نستخدم النموذج كاملاً
    if (!this.head) this.head = this.character;
    if (!this.mouth) this.mouth = this.character;
  }
  
  addModelLighting() {
    // إضاءة إضافية للنموذج
    const modelLight = new THREE.PointLight(0xff6b35, 1.5, 10);
    modelLight.position.set(0, 1.5, 2);
    this.scene.add(modelLight);
    this.modelLight = modelLight;
    
    // إضاءة من الخلف
    const backLight = new THREE.DirectionalLight(0x8b5cf6, 0.4);
    backLight.position.set(0, 2, -3);
    this.scene.add(backLight);
  }
  
  setupModelAnimations(gltf) {
    if (!gltf.animations || gltf.animations.length === 0) {
      // لا توجد أنيميشن في الملف، نستخدم حركات برمجية
      console.log('لا توجد أنيميشن في النموذج، سيتم استخدام حركات برمجية');
      return;
    }
    
    // إنشاء mixer للأنيميشن
    if (typeof THREE.AnimationMixer !== 'undefined') {
      this.mixer = new THREE.AnimationMixer(this.character);
      
      // تشغيل جميع الأنيميشن
      gltf.animations.forEach((clip) => {
        const action = this.mixer.clipAction(clip);
        action.play();
      });
      
      console.log(`✅ تم تحميل ${gltf.animations.length} أنيميشن`);
    }
  }
  
  centerModel() {
    // حساب مركز النموذج وضبط الكاميرا
    if (!this.character) return;
    
    const box = new THREE.Box3().setFromObject(this.character);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    
    // نقل النموذج إلى المركز
    this.character.position.x = -center.x;
    this.character.position.y = -center.y + 1.2;
    this.character.position.z = -center.z;
    
    // ضبط الكاميرا حسب حجم النموذج
    const maxDim = Math.max(size.x, size.y, size.z);
    const fov = this.camera.fov * (Math.PI / 180);
    let cameraZ = Math.abs(maxDim / 2 / Math.tan(fov / 2));
    cameraZ *= 1.5; // مسافة إضافية
    
    if (this.options.size === 'mini') {
      this.camera.position.set(0, 1.2, cameraZ * 0.8);
    } else if (this.options.size === 'small') {
      this.camera.position.set(0, 1.3, cameraZ);
    } else {
      this.camera.position.set(0, 1.5, cameraZ);
    }
    
    this.camera.lookAt(0, 1.2, 0);
  }
  
  createFallbackCharacter() {
    // إنشاء شخصية بسيطة كبديل في حالة فشل التحميل
    const group = new THREE.Group();
    
    // رأس بسيط
    const headGeometry = new THREE.SphereGeometry(0.35, 32, 32);
    const headMaterial = new THREE.MeshStandardMaterial({ 
      color: 0xffdbac,
      roughness: 0.3
    });
    const head = new THREE.Mesh(headGeometry, headMaterial);
    head.position.y = 1.5;
    group.add(head);
    this.head = head;
    
    // جسم
    const bodyGeometry = new THREE.CylinderGeometry(0.25, 0.3, 0.7, 16);
    const bodyMaterial = new THREE.MeshStandardMaterial({ 
      color: 0xf5f5f5
    });
    const body = new THREE.Mesh(bodyGeometry, bodyMaterial);
    body.position.y = 0.75;
    group.add(body);
    
    this.character = group;
    this.scene.add(group);
    
    console.log('⚠️ تم استخدام شخصية بديلة');
  }
  
  createAnimeCharacter() {
    // هذه الدالة لم تعد مستخدمة - تم استبدالها بـ loadGLBModel
    const group = new THREE.Group();
    
    // ========== الرأس (محسّن) ==========
    const headGeometry = new THREE.SphereGeometry(0.38, 32, 32);
    const headMaterial = new THREE.MeshStandardMaterial({ 
      color: 0xffdbac,
      roughness: 0.2,
      metalness: 0.05,
      normalScale: new THREE.Vector2(0.5, 0.5)
    });
    const head = new THREE.Mesh(headGeometry, headMaterial);
    head.position.y = 1.5;
    head.castShadow = true;
    head.receiveShadow = true;
    group.add(head);
    this.head = head;
    
    // ========== الشعر الأحمر (محسّن) ==========
    const hairGroup = new THREE.Group();
    
    // الشعر الرئيسي (أكثر تفصيلاً)
    const hairMainGeometry = new THREE.SphereGeometry(0.45, 32, 32);
    const hairMainMaterial = new THREE.MeshStandardMaterial({ 
      color: 0xff2d2d,
      emissive: 0xff4444,
      emissiveIntensity: 0.4,
      roughness: 0.3,
      metalness: 0.1
    });
    const hairMain = new THREE.Mesh(hairMainGeometry, hairMainMaterial);
    hairMain.position.y = 1.7;
    hairMain.scale.y = 1.4;
    hairMain.scale.x = 1.1;
    hairMain.castShadow = true;
    hairGroup.add(hairMain);
    
    // خصلات الشعر (أكثر وأطول)
    for (let i = 0; i < 12; i++) {
      const strandGeometry = new THREE.CylinderGeometry(0.025, 0.04, 0.4, 8);
      const strandMaterial = new THREE.MeshStandardMaterial({ 
        color: 0xff1a1a,
        emissive: 0xff3333,
        emissiveIntensity: 0.25,
        roughness: 0.3
      });
      const strand = new THREE.Mesh(strandGeometry, strandMaterial);
      const angle = (i / 12) * Math.PI * 2;
      const radius = 0.45 + (i % 3) * 0.05;
      strand.position.set(
        Math.cos(angle) * radius,
        1.35 + Math.sin(angle) * 0.25,
        Math.sin(angle) * 0.35
      );
      strand.rotation.z = angle + Math.PI / 2;
      strand.rotation.x = (Math.random() - 0.5) * 0.3;
      strand.castShadow = true;
      hairGroup.add(strand);
    }
    
    // خصلات جانبية طويلة
    for (let i = 0; i < 4; i++) {
      const longStrandGeometry = new THREE.CylinderGeometry(0.02, 0.035, 0.6, 8);
      const longStrandMaterial = new THREE.MeshStandardMaterial({ 
        color: 0xff1a1a,
        emissive: 0xff3333,
        emissiveIntensity: 0.3
      });
      const longStrand = new THREE.Mesh(longStrandGeometry, longStrandMaterial);
      const side = i < 2 ? -1 : 1;
      longStrand.position.set(
        side * 0.5,
        1.2 + (i % 2) * 0.3,
        0.2
      );
      longStrand.rotation.z = side * 0.5;
      longStrand.rotation.y = side * 0.3;
      longStrand.castShadow = true;
      hairGroup.add(longStrand);
    }
    
    group.add(hairGroup);
    this.hairGroup = hairGroup;
    
    // ========== العيون المتوهجة (محسّنة) ==========
    const eyeGroup = new THREE.Group();
    
    // خلفية العين (بيضاء)
    const eyeBaseGeometry = new THREE.SphereGeometry(0.13, 16, 16);
    const eyeBaseMaterial = new THREE.MeshStandardMaterial({ 
      color: 0xffffff,
      roughness: 0.1
    });
    const leftEyeBase = new THREE.Mesh(eyeBaseGeometry, eyeBaseMaterial);
    leftEyeBase.position.set(-0.15, 1.55, 0.32);
    eyeGroup.add(leftEyeBase);
    
    const rightEyeBase = new THREE.Mesh(eyeBaseGeometry, eyeBaseMaterial);
    rightEyeBase.position.set(0.15, 1.55, 0.32);
    eyeGroup.add(rightEyeBase);
    
    // العين اليسرى (متوهجة)
    const leftEyeGeometry = new THREE.SphereGeometry(0.12, 16, 16);
    const leftEyeMaterial = new THREE.MeshStandardMaterial({ 
      color: 0xff6b35,
      emissive: 0xff8c42,
      emissiveIntensity: 2.0,
      transparent: true,
      opacity: 0.95
    });
    const leftEye = new THREE.Mesh(leftEyeGeometry, leftEyeMaterial);
    leftEye.position.set(-0.15, 1.55, 0.33);
    eyeGroup.add(leftEye);
    
    // العين اليمنى
    const rightEye = new THREE.Mesh(leftEyeGeometry, leftEyeMaterial.clone());
    rightEye.position.set(0.15, 1.55, 0.33);
    eyeGroup.add(rightEye);
    
    // الحلقة الداخلية (قزحية) - متعددة الطبقات
    const irisOuterGeometry = new THREE.SphereGeometry(0.09, 16, 16);
    const irisOuterMaterial = new THREE.MeshStandardMaterial({ 
      color: 0xffaa00,
      emissive: 0xffcc00,
      emissiveIntensity: 2.5
    });
    const leftIrisOuter = new THREE.Mesh(irisOuterGeometry, irisOuterMaterial);
    leftIrisOuter.position.set(-0.15, 1.55, 0.35);
    eyeGroup.add(leftIrisOuter);
    
    const rightIrisOuter = new THREE.Mesh(irisOuterGeometry, irisOuterMaterial);
    rightIrisOuter.position.set(0.15, 1.55, 0.35);
    eyeGroup.add(rightIrisOuter);
    
    // الحلقة الداخلية (أصغر)
    const irisInnerGeometry = new THREE.SphereGeometry(0.07, 16, 16);
    const irisInnerMaterial = new THREE.MeshStandardMaterial({ 
      color: 0xffdd44,
      emissive: 0xffff00,
      emissiveIntensity: 3.0
    });
    const leftIrisInner = new THREE.Mesh(irisInnerGeometry, irisInnerMaterial);
    leftIrisInner.position.set(-0.15, 1.55, 0.36);
    eyeGroup.add(leftIrisInner);
    
    const rightIrisInner = new THREE.Mesh(irisInnerGeometry, irisInnerMaterial);
    rightIrisInner.position.set(0.15, 1.55, 0.36);
    eyeGroup.add(rightIrisInner);
    
    // البؤبؤ (أكبر قليلاً)
    const pupilGeometry = new THREE.SphereGeometry(0.04, 16, 16);
    const pupilMaterial = new THREE.MeshStandardMaterial({ 
      color: 0x000000,
      emissive: 0x111111,
      emissiveIntensity: 0.5
    });
    const leftPupil = new THREE.Mesh(pupilGeometry, pupilMaterial);
    leftPupil.position.set(-0.15, 1.55, 0.37);
    eyeGroup.add(leftPupil);
    
    const rightPupil = new THREE.Mesh(pupilGeometry, pupilMaterial);
    rightPupil.position.set(0.15, 1.55, 0.37);
    eyeGroup.add(rightPupil);
    
    // بريق في العين
    const sparkleGeometry = new THREE.SphereGeometry(0.015, 8, 8);
    const sparkleMaterial = new THREE.MeshStandardMaterial({ 
      color: 0xffffff,
      emissive: 0xffffff,
      emissiveIntensity: 5.0
    });
    const leftSparkle = new THREE.Mesh(sparkleGeometry, sparkleMaterial);
    leftSparkle.position.set(-0.12, 1.58, 0.38);
    eyeGroup.add(leftSparkle);
    
    const rightSparkle = new THREE.Mesh(sparkleGeometry, sparkleMaterial);
    rightSparkle.position.set(0.18, 1.58, 0.38);
    eyeGroup.add(rightSparkle);
    
    group.add(eyeGroup);
    this.eyeGroup = eyeGroup;
    this.leftEye = leftEye;
    this.rightEye = rightEye;
    this.leftPupil = leftPupil;
    this.rightPupil = rightPupil;
    
    // ========== الفم (محسّن) ==========
    const mouthGeometry = new THREE.TorusGeometry(0.07, 0.018, 8, 16);
    const mouthMaterial = new THREE.MeshStandardMaterial({ 
      color: 0xcc6666,
      roughness: 0.4
    });
    const mouth = new THREE.Mesh(mouthGeometry, mouthMaterial);
    mouth.position.set(0, 1.42, 0.33);
    mouth.rotation.x = Math.PI / 2;
    group.add(mouth);
    this.mouth = mouth;
    
    // ========== الخدود (للطابع الأنمي) ==========
    const cheekGeometry = new THREE.SphereGeometry(0.08, 16, 16);
    const cheekMaterial = new THREE.MeshStandardMaterial({ 
      color: 0xffb3b3,
      transparent: true,
      opacity: 0.6
    });
    const leftCheek = new THREE.Mesh(cheekGeometry, cheekMaterial);
    leftCheek.position.set(-0.25, 1.45, 0.28);
    leftCheek.scale.x = 1.5;
    group.add(leftCheek);
    
    const rightCheek = new THREE.Mesh(cheekGeometry, cheekMaterial);
    rightCheek.position.set(0.25, 1.45, 0.28);
    rightCheek.scale.x = 1.5;
    group.add(rightCheek);
    
    // ========== الجسم (محسّن) ==========
    const bodyGeometry = new THREE.CylinderGeometry(0.26, 0.32, 0.75, 16);
    const bodyMaterial = new THREE.MeshStandardMaterial({ 
      color: 0xf5f5f5,
      roughness: 0.5,
      metalness: 0.1
    });
    const body = new THREE.Mesh(bodyGeometry, bodyMaterial);
    body.position.y = 0.8;
    body.castShadow = true;
    body.receiveShadow = true;
    group.add(body);
    this.body = body;
    
    // ========== الياقة/الطوق ==========
    const collarGeometry = new THREE.TorusGeometry(0.28, 0.03, 8, 16);
    const collarMaterial = new THREE.MeshStandardMaterial({ 
      color: 0x8b5cf6,
      emissive: 0x8b5cf6,
      emissiveIntensity: 0.3
    });
    const collar = new THREE.Mesh(collarGeometry, collarMaterial);
    collar.position.y = 1.15;
    collar.rotation.x = Math.PI / 2;
    group.add(collar);
    
    // ========== الأذرع ==========
    const armGeometry = new THREE.CylinderGeometry(0.08, 0.1, 0.4, 8);
    const armMaterial = new THREE.MeshStandardMaterial({ 
      color: 0xffdbac,
      roughness: 0.3
    });
    
    // الذراع الأيسر
    const leftArm = new THREE.Mesh(armGeometry, armMaterial);
    leftArm.position.set(-0.3, 0.9, 0);
    leftArm.rotation.z = 0.3;
    leftArm.castShadow = true;
    group.add(leftArm);
    this.leftArm = leftArm;
    
    // الذراع الأيمن
    const rightArm = new THREE.Mesh(armGeometry, armMaterial);
    rightArm.position.set(0.3, 0.9, 0);
    rightArm.rotation.z = -0.3;
    rightArm.castShadow = true;
    group.add(rightArm);
    this.rightArm = rightArm;
    
    // ========== اليدين ==========
    const handGeometry = new THREE.SphereGeometry(0.1, 16, 16);
    const handMaterial = new THREE.MeshStandardMaterial({ 
      color: 0xffdbac,
      roughness: 0.3
    });
    
    const leftHand = new THREE.Mesh(handGeometry, handMaterial);
    leftHand.position.set(-0.35, 0.7, 0.1);
    leftHand.castShadow = true;
    group.add(leftHand);
    this.leftHand = leftHand;
    
    const rightHand = new THREE.Mesh(handGeometry, handMaterial);
    rightHand.position.set(0.35, 0.7, 0.1);
    rightHand.castShadow = true;
    group.add(rightHand);
    this.rightHand = rightHand;
    
    // ========== الهالة السحرية (محسّنة) ==========
    const haloGroup = new THREE.Group();
    
    // الهالة الرئيسية
    const haloGeometry = new THREE.TorusGeometry(0.55, 0.1, 8, 32);
    const haloMaterial = new THREE.MeshStandardMaterial({ 
      color: 0x8b5cf6,
      emissive: 0x8b5cf6,
      emissiveIntensity: 1.0,
      transparent: true,
      opacity: 0.7
    });
    const halo = new THREE.Mesh(haloGeometry, haloMaterial);
    halo.position.y = 1.95;
    halo.rotation.x = Math.PI / 2;
    haloGroup.add(halo);
    
    // حلقة داخلية أصغر
    const innerHaloGeometry = new THREE.TorusGeometry(0.5, 0.06, 8, 32);
    const innerHaloMaterial = new THREE.MeshStandardMaterial({ 
      color: 0xa78bfa,
      emissive: 0xa78bfa,
      emissiveIntensity: 1.2,
      transparent: true,
      opacity: 0.8
    });
    const innerHalo = new THREE.Mesh(innerHaloGeometry, innerHaloMaterial);
    innerHalo.position.y = 1.95;
    innerHalo.rotation.x = Math.PI / 2;
    haloGroup.add(innerHalo);
    
    // جزيئات سحرية
    for (let i = 0; i < 8; i++) {
      const particleGeometry = new THREE.SphereGeometry(0.02, 8, 8);
      const particleMaterial = new THREE.MeshStandardMaterial({ 
        color: 0x8b5cf6,
        emissive: 0x8b5cf6,
        emissiveIntensity: 2.0,
        transparent: true,
        opacity: 0.8
      });
      const particle = new THREE.Mesh(particleGeometry, particleMaterial);
      const angle = (i / 8) * Math.PI * 2;
      particle.position.set(
        Math.cos(angle) * 0.6,
        1.95 + Math.sin(angle) * 0.1,
        Math.sin(angle) * 0.1
      );
      haloGroup.add(particle);
    }
    
    group.add(haloGroup);
    this.halo = haloGroup;
    
    // ========== الغربان (محسّنة) ==========
    const crowGroup = new THREE.Group();
    for (let i = 0; i < 4; i++) {
      // الجسم
      const bodyGeometry = new THREE.ConeGeometry(0.12, 0.25, 8);
      const bodyMaterial = new THREE.MeshStandardMaterial({ 
        color: 0x1a1a1a,
        emissive: 0x000000,
        roughness: 0.9,
        metalness: 0.1
      });
      const crowBody = new THREE.Mesh(bodyGeometry, bodyMaterial);
      
      // الرأس
      const headGeometry = new THREE.SphereGeometry(0.08, 8, 8);
      const headMaterial = new THREE.MeshStandardMaterial({ 
        color: 0x0a0a0a,
        roughness: 0.9
      });
      const crowHead = new THREE.Mesh(headGeometry, headMaterial);
      crowHead.position.y = 0.15;
      
      // المنقار
      const beakGeometry = new THREE.ConeGeometry(0.02, 0.05, 6);
      const beakMaterial = new THREE.MeshStandardMaterial({ 
        color: 0x333333,
        roughness: 0.5
      });
      const beak = new THREE.Mesh(beakGeometry, beakMaterial);
      beak.position.set(0, 0.18, 0.08);
      beak.rotation.x = -Math.PI / 4;
      
      // الأجنحة
      const wingGeometry = new THREE.PlaneGeometry(0.15, 0.2);
      const wingMaterial = new THREE.MeshStandardMaterial({ 
        color: 0x1a1a1a,
        side: THREE.DoubleSide,
        roughness: 0.9
      });
      const leftWing = new THREE.Mesh(wingGeometry, wingMaterial);
      leftWing.position.set(-0.1, 0, 0);
      leftWing.rotation.y = -Math.PI / 4;
      
      const rightWing = new THREE.Mesh(wingGeometry, wingMaterial);
      rightWing.position.set(0.1, 0, 0);
      rightWing.rotation.y = Math.PI / 4;
      
      const crow = new THREE.Group();
      crow.add(crowBody);
      crow.add(crowHead);
      crow.add(beak);
      crow.add(leftWing);
      crow.add(rightWing);
      
      const angle = (i / 4) * Math.PI * 2;
      crow.position.set(
        Math.cos(angle) * 1.8,
        1.1 + Math.sin(angle) * 0.4,
        Math.sin(angle) * 0.6 - 1.2
      );
      crow.rotation.z = angle;
      crow.rotation.y = angle + Math.PI / 2;
      crow.castShadow = true;
      
      crowGroup.add(crow);
    }
    group.add(crowGroup);
    this.crowGroup = crowGroup;
    
    this.character = group;
    this.scene.add(group);
  }
  
  animate() {
    this.animationId = requestAnimationFrame(() => this.animate());
    
    // تحديث mixer الأنيميشن
    if (this.mixer) {
      this.mixer.update(0.016); // ~60fps
    }
    
    if (!this.character) return;
    
    const time = Date.now() * 0.001;
    
    // حركة التوقف (تنفس طبيعي)
    if (!this.isSpeaking) {
      this.character.rotation.y = Math.sin(time * 0.4) * 0.08;
      this.character.position.y = Math.sin(time * 0.6) * 0.04;
      
      // حركة الرأس (نظر خفيف)
      if (this.head && this.head !== this.character) {
        this.head.rotation.y = Math.sin(time * 0.3) * 0.05;
        this.head.rotation.x = Math.sin(time * 0.2) * 0.02;
      }
    }
    
    // حركة الشعر (أكثر طبيعية)
    if (this.hairGroup) {
      this.hairGroup.rotation.y = Math.sin(time * 0.25) * 0.04;
      this.hairGroup.children.forEach((strand, i) => {
        if (strand.geometry.type === 'CylinderGeometry') {
          strand.rotation.y = Math.sin(time * 0.4 + i * 0.5) * 0.15;
          strand.rotation.x = Math.sin(time * 0.3 + i * 0.3) * 0.1;
          strand.position.y += Math.sin(time * 0.5 + i) * 0.02;
        }
      });
    }
    
    // حركة العيون (وميض طبيعي) - فقط إذا كانت موجودة
    if (this.eyeGroup && this.eyeGroup.children.length > 0 && Math.random() < 0.008) {
      this.eyeGroup.children.forEach(eye => {
        if (eye.scale) {
          eye.scale.y = 0.05;
          setTimeout(() => {
            if (eye.scale) eye.scale.y = 1;
          }, 150);
        }
      });
    }
    
    // حركة البؤبؤ (تتبع) - فقط إذا كانت موجودة
    if (this.leftPupil && this.rightPupil) {
      const mouseX = (Math.sin(time * 0.2) - 0.5) * 0.02;
      const mouseY = (Math.cos(time * 0.15) - 0.5) * 0.02;
      this.leftPupil.position.x = -0.15 + mouseX;
      this.leftPupil.position.y = 1.55 + mouseY;
      this.rightPupil.position.x = 0.15 + mouseX;
      this.rightPupil.position.y = 1.55 + mouseY;
    }
    
    // حركة الهالة (دوران سحري)
    if (this.halo) {
      this.halo.rotation.z += 0.008;
      if (this.halo.position) {
        this.halo.position.y = 1.95 + Math.sin(time * 1.5) * 0.06;
      }
      // حركة الجزيئات
      this.halo.children.forEach((child, i) => {
        if (child.geometry && child.geometry.type === 'SphereGeometry') {
          const angle = (i / 8) * Math.PI * 2 + time;
          child.position.x = Math.cos(angle) * 0.6;
          child.position.z = Math.sin(angle) * 0.1;
          child.position.y = 1.95 + Math.sin(time * 2 + i) * 0.1;
          child.rotation.y += 0.02;
        }
      });
    }
    
    // حركة الغربان (طيران)
    if (this.crowGroup) {
      this.crowGroup.children.forEach((crow, i) => {
        crow.rotation.y += 0.003;
        crow.position.y = 1.1 + Math.sin(time * 0.4 + i) * 0.15;
        crow.position.x += Math.sin(time * 0.3 + i) * 0.02;
        
        // حركة الأجنحة
        if (crow.children.length > 3) {
          const leftWing = crow.children[3];
          const rightWing = crow.children[4];
          if (leftWing && rightWing) {
            leftWing.rotation.x = Math.sin(time * 2 + i) * 0.3;
            rightWing.rotation.x = -Math.sin(time * 2 + i) * 0.3;
          }
        }
      });
    }
    
    // حركة الأذرع (طبيعية) - إذا كانت موجودة
    if (this.arms && this.arms.length >= 2) {
      this.arms[0].rotation.z = 0.3 + Math.sin(time * 0.5) * 0.05;
      this.arms[1].rotation.z = -0.3 - Math.sin(time * 0.5) * 0.05;
    } else if (this.leftArm && this.rightArm) {
      this.leftArm.rotation.z = 0.3 + Math.sin(time * 0.5) * 0.05;
      this.rightArm.rotation.z = -0.3 - Math.sin(time * 0.5) * 0.05;
    }
    
    // إضاءة العيون (نبض قوي)
    if (this.eyeLight) {
      this.eyeLight.intensity = 1.8 + Math.sin(time * 2.5) * 0.4;
      this.eyeLight.position.x = Math.sin(time * 0.3) * 0.1;
      this.eyeLight.position.y = 1.5 + Math.sin(time * 0.2) * 0.1;
    }
    
    // إضاءة الشعر (توهج)
    if (this.hairLight) {
      this.hairLight.intensity = 0.9 + Math.sin(time * 1.5) * 0.2;
      this.hairLight.position.y = 1.8 + Math.sin(time) * 0.05;
    }
    
    // إضاءة الهالة
    if (this.haloLight) {
      this.haloLight.intensity = 0.8 + Math.sin(time * 2) * 0.2;
      this.haloLight.position.y = 1.95 + Math.sin(time * 1.5) * 0.05;
    }
    
    // حركة الجزيئات في الخلفية
    if (this.particleGroup) {
      this.particleGroup.children.forEach((particle) => {
        particle.position.y += particle.userData.speed;
        particle.rotation.y += particle.userData.rotationSpeed;
        
        if (particle.position.y > 5) {
          particle.position.y = -5;
        }
        
        // توهج متغير
        const opacity = 0.4 + Math.sin(time * 2 + particle.position.x) * 0.3;
        particle.material.opacity = opacity;
      });
    }
    
    this.renderer.render(this.scene, this.camera);
  }
  
  speak(text, lang = 'ar') {
    if (!this.voiceEnabled) return;
    
    this.isSpeaking = true;
    this.currentMood = 'speaking';
    
    // حركة التحدث الطبيعية (محسّنة جداً)
    if (this.mouth) {
      let frameCount = 0;
      const talkInterval = setInterval(() => {
        if (this.mouth && this.isSpeaking) {
          frameCount++;
          const time = frameCount * 0.05;
          
          // حركة الفم الطبيعية (فتح وإغلاق)
          const mouthOpen = Math.abs(Math.sin(time * 2)) * 0.5;
          this.mouth.scale.y = 1 + mouthOpen * 0.6;
          this.mouth.scale.x = 1 + Math.cos(time * 1.5) * 0.15;
          
          // حركة دوران طفيفة
          this.mouth.rotation.x = Math.PI / 2 + Math.sin(time * 1.8) * 0.25;
          this.mouth.rotation.z = Math.sin(time * 0.7) * 0.1;
          
          // حركة عمودية طفيفة
          if (this.mouth.position) {
            this.mouth.position.z = 0.33 + Math.sin(time * 2.2) * 0.02;
          }
        } else {
          clearInterval(talkInterval);
        }
      }, 16);
      
      const duration = Math.max(text.length * 100, 2000);
      setTimeout(() => {
        clearInterval(talkInterval);
        if (this.mouth) {
          // إغلاق الفم بسلاسة
          const closeInterval = setInterval(() => {
            if (this.mouth.scale.y > 1) {
              this.mouth.scale.y *= 0.9;
              this.mouth.scale.x *= 0.95;
            } else {
              clearInterval(closeInterval);
              this.mouth.scale.y = 1;
              this.mouth.scale.x = 1;
              this.mouth.rotation.x = Math.PI / 2;
              this.mouth.rotation.z = 0;
              if (this.mouth.position) {
                this.mouth.position.z = 0.33;
              }
            }
          }, 50);
        }
        this.isSpeaking = false;
        this.currentMood = 'neutral';
      }, duration);
    }
    
    // حركة الرأس والجسم الطبيعية (محسّنة)
    if (this.character) {
      const originalY = this.character.position.y;
      const originalRotY = this.character.rotation.y;
      const originalRotX = this.character.rotation.x || 0;
      let headFrame = 0;
      
      const talkBounce = setInterval(() => {
        if (this.character && this.isSpeaking) {
          headFrame++;
          const time = headFrame * 0.02;
          
          // حركة تنفس أثناء التحدث
          this.character.position.y = originalY + Math.sin(time * 1.2) * 0.08;
          
          // حركة رأس طبيعية (إيماءات)
          this.character.rotation.y = originalRotY + Math.sin(time * 0.4) * 0.12;
          this.character.rotation.x = originalRotX + Math.sin(time * 0.3) * 0.05;
          
          // حركة خفيفة للجسم
          if (this.body) {
            this.body.rotation.z = Math.sin(time * 0.5) * 0.03;
          }
        } else {
          clearInterval(talkBounce);
        }
      }, 16);
    }
    
    // حركة الرأس مباشرة (إذا كان منفصلاً)
    if (this.head && this.head !== this.character) {
      const headTalkInterval = setInterval(() => {
        if (this.isSpeaking && this.head) {
          const time = Date.now() * 0.015;
          this.head.rotation.y = Math.sin(time * 0.6) * 0.1;
          this.head.rotation.x = Math.sin(time * 0.4) * 0.05;
        } else {
          clearInterval(headTalkInterval);
        }
      }, 16);
    }
    
    // حركة الأذرع الطبيعية أثناء التحدث
    if (this.arms && this.arms.length >= 2) {
      const armInterval = setInterval(() => {
        if (this.isSpeaking && this.arms) {
          const time = Date.now() * 0.012;
          this.arms[0].rotation.z = 0.3 + Math.sin(time) * 0.12;
          this.arms[0].rotation.x = Math.sin(time * 0.7) * 0.05;
          this.arms[1].rotation.z = -0.3 - Math.sin(time) * 0.12;
          this.arms[1].rotation.x = -Math.sin(time * 0.7) * 0.05;
        } else {
          clearInterval(armInterval);
        }
      }, 16);
    } else if (this.leftArm && this.rightArm) {
      const armInterval = setInterval(() => {
        if (this.isSpeaking && this.leftArm && this.rightArm) {
          const time = Date.now() * 0.012;
          this.leftArm.rotation.z = 0.3 + Math.sin(time) * 0.12;
          this.leftArm.rotation.x = Math.sin(time * 0.7) * 0.05;
          this.rightArm.rotation.z = -0.3 - Math.sin(time) * 0.12;
          this.rightArm.rotation.x = -Math.sin(time * 0.7) * 0.05;
        } else {
          clearInterval(armInterval);
        }
      }, 16);
    }
    
    // حركة اليدين (إيماءات)
    if (this.leftHand && this.rightHand) {
      const handInterval = setInterval(() => {
        if (this.isSpeaking && this.leftHand && this.rightHand) {
          const time = Date.now() * 0.01;
          this.leftHand.rotation.y = Math.sin(time) * 0.2;
          this.rightHand.rotation.y = -Math.sin(time) * 0.2;
        } else {
          clearInterval(handInterval);
        }
      }, 16);
    }
    
    // توهج العيون الطبيعية أثناء التحدث
    if (this.eyeLight) {
      const originalIntensity = this.eyeLight.intensity || 2.0;
      let glowFrame = 0;
      const glowInterval = setInterval(() => {
        if (this.isSpeaking && this.eyeLight) {
          glowFrame++;
          const time = glowFrame * 0.03;
          // نبض ناعم
          this.eyeLight.intensity = originalIntensity + Math.sin(time * 2) * 0.4;
          // تغيير لون طفيف
          const hueShift = Math.sin(time) * 0.1;
          this.eyeLight.color.setHSL(0.08 + hueShift, 0.8, 0.6);
        } else {
          clearInterval(glowInterval);
          if (this.eyeLight) {
            this.eyeLight.intensity = originalIntensity;
            this.eyeLight.color.setHex(0xff6b35);
          }
        }
      }, 16);
    }
    
    // حركة العيون (وميض أثناء التحدث)
    if (this.eyeGroup) {
      const blinkInterval = setInterval(() => {
        if (this.isSpeaking && this.eyeGroup && Math.random() < 0.3) {
          this.eyeGroup.children.forEach(eye => {
            if (eye.scale) {
              eye.scale.y = 0.1;
              setTimeout(() => {
                if (eye.scale) eye.scale.y = 1;
              }, 100);
            }
          });
        } else if (!this.isSpeaking) {
          clearInterval(blinkInterval);
        }
      }, 2000);
    }
    
    // Text-to-Speech محسّن
    if ('speechSynthesis' in window) {
      speechSynthesis.cancel();
      
      // البحث عن صوت عربي أفضل
      const voices = speechSynthesis.getVoices();
      let selectedVoice = null;
      
      // محاولة العثور على صوت عربي
      for (let voice of voices) {
        if (lang === 'ar' && (voice.lang.includes('ar') || voice.name.includes('Arabic'))) {
          selectedVoice = voice;
          break;
        } else if (lang !== 'ar' && voice.lang.includes(lang)) {
          selectedVoice = voice;
          break;
        }
      }
      
      const utterance = new SpeechSynthesisUtterance(text);
      
      if (selectedVoice) {
        utterance.voice = selectedVoice;
      }
      
      utterance.lang = lang === 'ar' ? 'ar-SA' : 'en-US';
      utterance.rate = 0.88; // سرعة طبيعية
      utterance.pitch = 1.2; // نبرة أعلى قليلاً (أنثوية)
      utterance.volume = 1;
      
      // تحسينات إضافية
      utterance.onstart = () => {
        // تأثير بصري عند بدء التحدث
        if (this.eyeGroup) {
          this.eyeGroup.children.forEach(eye => {
            if (eye.scale) {
              eye.scale.set(1.15, 1.15, 1.15);
              setTimeout(() => {
                if (eye.scale) eye.scale.set(1, 1, 1);
              }, 300);
            }
          });
        }
        
        // توهج إضافي
        if (this.eyeLight) {
          this.eyeLight.intensity = 2.5;
        }
      };
      
      utterance.onend = () => {
        this.isSpeaking = false;
        this.currentMood = 'neutral';
        
        // إعادة تعيين الإضاءة
        if (this.eyeLight) {
          this.eyeLight.intensity = 2.0;
        }
      };
      
      utterance.onerror = (error) => {
        console.error('Speech error:', error);
        this.isSpeaking = false;
        this.currentMood = 'neutral';
      };
      
      // تحميل الأصوات إذا لم تكن جاهزة
      if (voices.length === 0) {
        speechSynthesis.onvoiceschanged = () => {
          const newVoices = speechSynthesis.getVoices();
          for (let voice of newVoices) {
            if (lang === 'ar' && (voice.lang.includes('ar') || voice.name.includes('Arabic'))) {
              utterance.voice = voice;
              break;
            }
          }
          speechSynthesis.speak(utterance);
        };
      } else {
        speechSynthesis.speak(utterance);
      }
    }
  }
  
  pointAt(element) {
    // إشارة إلى عنصر معين
    if (!this.character) return;
    
    const rect = element.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    
    // حساب الزاوية
    const canvasRect = this.canvas.getBoundingClientRect();
    const canvasCenterX = canvasRect.left + canvasRect.width / 2;
    const canvasCenterY = canvasRect.top + canvasRect.height / 2;
    
    const angle = Math.atan2(
      centerY - canvasCenterY,
      centerX - canvasCenterX
    );
    
    // تحريك الرأس
    if (this.character) {
      this.character.rotation.y = angle - Math.PI / 2;
    }
    
    // إظهار مؤشر
    this.showPointer(element);
  }
  
  showPointer(element) {
    // إزالة المؤشرات السابقة
    document.querySelectorAll('.assistant-pointer').forEach(p => p.remove());
    
    const pointer = document.createElement('div');
    pointer.className = 'assistant-pointer';
    pointer.style.cssText = `
      position: absolute;
      width: 30px;
      height: 30px;
      border: 3px solid #ff6b35;
      border-radius: 50%;
      background: rgba(255, 107, 53, 0.2);
      pointer-events: none;
      z-index: 10000;
      animation: assistantPulse 1s infinite;
      box-shadow: 0 0 20px rgba(255, 107, 53, 0.8);
    `;
    
    const rect = element.getBoundingClientRect();
    pointer.style.left = (rect.left + rect.width / 2 - 15) + 'px';
    pointer.style.top = (rect.top - 40) + 'px';
    
    document.body.appendChild(pointer);
    
    setTimeout(() => pointer.remove(), 3000);
  }
  
  highlightError(element, message) {
    // تسليط الضوء على خطأ
    element.style.transition = 'all 0.3s ease';
    element.style.boxShadow = '0 0 20px rgba(239, 68, 68, 0.8)';
    element.style.border = '2px solid #ef4444';
    
    // إضافة tooltip
    const tooltip = document.createElement('div');
    tooltip.className = 'assistant-error-tooltip';
    tooltip.textContent = message;
    tooltip.style.cssText = `
      position: absolute;
      background: rgba(239, 68, 68, 0.95);
      color: white;
      padding: 8px 12px;
      border-radius: 8px;
      font-size: 12px;
      z-index: 10001;
      pointer-events: none;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    `;
    
    const rect = element.getBoundingClientRect();
    tooltip.style.left = rect.left + 'px';
    tooltip.style.top = (rect.top - 40) + 'px';
    
    document.body.appendChild(tooltip);
    
    this.pointAt(element);
    this.speak(message);
    
    setTimeout(() => {
      element.style.boxShadow = '';
      element.style.border = '';
      tooltip.remove();
    }, 5000);
  }
  
  setupInteractions() {
    // تفاعل مع النقر
    this.canvas.addEventListener('click', () => {
      this.greet();
    });
  }
  
  greet() {
    const timeOfDay = new Date().getHours();
    let greeting = '';
    
    if (timeOfDay >= 5 && timeOfDay < 12) {
      greeting = 'صباح الخير! أنا المساعد الذكي. جاهزة لمساعدتك في تحليل البيانات وإيجاد الأخطاء.';
    } else if (timeOfDay >= 12 && timeOfDay < 17) {
      greeting = 'مساء الخير! أنا هنا لمساعدتك في مراقبة النظام وتحليل البيانات.';
    } else if (timeOfDay >= 17 && timeOfDay < 21) {
      greeting = 'مساء الخير! جاهزة لمساعدتك في تحليل البيانات وإعطاء التقارير.';
    } else {
      greeting = 'أهلاً! حتى في هذا الوقت المتأخر، أنا هنا لمساعدتك.';
    }
    
    this.speak(greeting);
    this.showHappyState();
  }
  
  intelligentResponse(context) {
    // ردود ذكية حسب السياق
    const responses = {
      'analysis_complete': [
        'تم التحليل بنجاح! وجدت بعض النقاط التي تحتاج إلى انتباهك.',
        'انتهى التحليل. لدي بعض الملاحظات المهمة.',
        'التحليل جاهز! اكتشفت بعض المشاكل التي يجب معالجتها.'
      ],
      'no_issues': [
        'رائع! كل شيء يبدو مثالياً. لا توجد مشاكل.',
        'ممتاز! النظام يعمل بشكل صحيح.',
        'لا توجد مشاكل! كل شيء على ما يرام.'
      ],
      'critical_issue': [
        'تنبيه عاجل! وجدت مشكلة حرجة تحتاج إلى معالجة فورية.',
        'هناك مشكلة خطيرة! يجب معالجتها الآن.',
        'انتبه! اكتشفت مشكلة حرجة في النظام.'
      ]
    };
    
    const category = responses[context] || responses['analysis_complete'];
    return category[Math.floor(Math.random() * category.length)];
  }
  
  async startAutoAnalysis() {
    // تحليل تلقائي كل 30 ثانية
    setInterval(async () => {
      await this.analyzePage();
    }, 30000);
    
    // تحليل فوري عند التحميل
    setTimeout(() => {
      this.analyzePage();
    }, 2000);
  }
  
  async analyzePage() {
    try {
      const response = await fetch('/assistant/analyze-page');
      const data = await response.json();
      
      if (data.success && data.issues && data.issues.length > 0) {
        this.issues = data.issues;
        this.reportIssues(data.issues);
      }
    } catch (error) {
      console.error('Analysis error:', error);
    }
  }
  
  reportIssues(issues) {
    const critical = issues.filter(i => i.severity === 'critical');
    const warnings = issues.filter(i => i.severity === 'warning');
    
    if (critical.length > 0) {
      this.speak(`تنبيه! يوجد ${critical.length} مشكلة حرجة في الصفحة.`);
      critical.forEach(issue => {
        const element = document.querySelector(issue.selector);
        if (element) {
          this.highlightError(element, issue.message);
        }
      });
    } else if (warnings.length > 0) {
      this.speak(`يوجد ${warnings.length} تحذير في الصفحة.`);
    }
  }
  
  resize() {
    if (!this.container || !this.camera || !this.renderer) return;
    
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }
  
  destroy() {
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
    }
    if (this.renderer) {
      this.renderer.dispose();
    }
    speechSynthesis.cancel();
  }
}

// CSS للأنيميشن
const style = document.createElement('style');
style.textContent = `
  @keyframes assistantPulse {
    0%, 100% { transform: scale(1); opacity: 1; }
    50% { transform: scale(1.2); opacity: 0.7; }
  }
`;
document.head.appendChild(style);

// Export
if (typeof module !== 'undefined' && module.exports) {
  module.exports = AssistantCharacter;
}
