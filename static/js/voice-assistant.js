/**
 * Voice Assistant - مساعد صوتي ذكي محسّن بشكل شامل
 * يدعم الأوامر العربية للتحكم الكامل في الموقع مع مؤشر تردد حي
 */

class VoiceAssistant {
    constructor() {
        this.recognition = null;
        this.continuousRecognition = null;
        this.synthesis = window.speechSynthesis;
        this.isListening = false;
        this.isAlwaysListening = false;
        this.currentPage = window.location.pathname;
        this.wakeWord = 'نعم';
        this.wakeWordDetected = false;
        this.audioContext = null;
        this.analyser = null;
        this.microphone = null;
        this.dataArray = null;
        this.animationFrame = null;
        this.volumeLevel = 0;
        this.isSpeaking = false;
        this.speechVolumeLevel = 0;
        this.init();
        this.initContinuousListening();
        this.initAudioVisualizer();
    }

    async initAudioVisualizer() {
        try {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 512;
            this.analyser.smoothingTimeConstant = 0.8;
            this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);
            
            // Try to get microphone access for real-time visualization
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                this.microphone = this.audioContext.createMediaStreamSource(stream);
                this.microphone.connect(this.analyser);
            } catch (e) {
                console.warn('Microphone access not available for visualization:', e);
            }
        } catch (e) {
            console.warn('Audio visualizer not supported:', e);
        }
    }

    startVisualizer() {
        if (this.animationFrame) return;
        
        const visualize = () => {
            if (!this.isListening && !this.isAlwaysListening && !this.isSpeaking) {
                this.animationFrame = null;
                this.updateVisualizer(0, 0);
                return;
            }
            
            if (this.analyser) {
                this.analyser.getByteFrequencyData(this.dataArray);
                const average = this.dataArray.reduce((a, b) => a + b) / this.dataArray.length;
                this.volumeLevel = Math.min(1, average / 150);
            } else {
                // Simulate visualization when speaking
                if (this.isSpeaking) {
                    this.volumeLevel = 0.3 + Math.random() * 0.4;
                } else {
                    this.volumeLevel = Math.max(0, this.volumeLevel - 0.05);
                }
            }
            
            this.updateVisualizer(this.volumeLevel, this.speechVolumeLevel);
            this.animationFrame = requestAnimationFrame(visualize);
        };
        
        visualize();
    }

    updateVisualizer(listenLevel, speakLevel) {
        const visualizer = document.getElementById('voiceVisualizer');
        if (!visualizer) return;
        
        const bars = visualizer.querySelectorAll('.viz-bar');
        const barCount = bars.length;
        const activeLevel = this.isSpeaking ? speakLevel : listenLevel;
        
        bars.forEach((bar, index) => {
            const threshold = index / barCount;
            const height = activeLevel > threshold ? Math.min(100, (activeLevel - threshold) * 300) : Math.max(5, activeLevel * 20);
            bar.style.height = `${height}%`;
            bar.style.opacity = activeLevel > 0.05 ? Math.min(1, 0.3 + activeLevel * 0.7) : 0.2;
            bar.style.transition = 'height 0.05s ease, opacity 0.1s ease';
        });
    }

    init() {
        if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
            console.warn('Voice recognition not supported');
            return;
        }

        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        this.recognition = new SpeechRecognition();
        
        // تحسين إعدادات اللغة العربية
        const arabicLangs = ['ar-SA', 'ar-EG', 'ar-AE', 'ar-IQ', 'ar'];
        let langSet = false;
        for (const lang of arabicLangs) {
            try {
                this.recognition.lang = lang;
                langSet = true;
                console.log('Set recognition language to:', lang);
                break;
            } catch (e) {
                continue;
            }
        }
        if (!langSet) {
            this.recognition.lang = 'en-US';
            console.warn('Arabic not supported, using English');
        }
        
        this.recognition.continuous = false;
        this.recognition.interimResults = true; // تفعيل النتائج المؤقتة لرؤية النص أثناء الكلام
        this.recognition.maxAlternatives = 10;
        
        // إضافة timeout أطول للاستماع
        if (this.recognition.serviceURI) {
            // Chrome specific
            this.recognition.grammars = null;
        }

        this.recognition.onstart = () => {
            this.isListening = true;
            this.updateUI('listening');
            this.startVisualizer();
            // لا نقول أي شيء، فقط نستمع
        };

        this.recognition.onresult = (event) => {
            let command = '';
            let confidence = 0;
            let interimText = '';
            
            // معالجة جميع النتائج (interim + final)
            for (let i = 0; i < event.results.length; i++) {
                const result = event.results[i];
                const transcript = result[0].transcript.trim();
                
                if (!result.isFinal) {
                    // نتائج مؤقتة - عرضها مباشرة
                    interimText = transcript;
                    this.updateSpeechDisplay(transcript || 'جاري الاستماع...', true);
                    continue;
                }
                
                // نتائج نهائية - معالجتها
                if (result[0] && result[0].length > 0) {
                    for (let j = 0; j < Math.min(10, result[0].length); j++) {
                        const alt = result[0][j];
                        const altTranscript = alt.transcript.trim();
                        const altConfidence = alt.confidence || (1 - j * 0.1);
                        
                        if (altTranscript && altTranscript.length > 0 && altConfidence > confidence) {
                            command = altTranscript;
                            confidence = altConfidence;
                        }
                    }
                }
            }
            
            // إذا كان هناك أمر نهائي، معالجته
            if (command && command.length > 0) {
                this.updateSpeechDisplay(command);
                console.log('Voice command:', command, 'Confidence:', confidence);
                this.processCommand(command);
            } else if (interimText) {
                // إذا كان هناك نص مؤقت فقط، ننتظر المزيد
                this.updateSpeechDisplay(interimText, true);
            } else {
                this.updateSpeechDisplay('لم أتمكن من فهم الأمر، جرب مرة أخرى');
                this.speak('لم أتمكن من فهم الأمر، جرب مرة أخرى', 0.85);
            }
        };

        this.recognition.onerror = (event) => {
            console.error('Recognition error:', event.error);
            this.isListening = false;
            this.updateUI(this.isAlwaysListening ? 'waiting' : 'idle');
            
            if (event.error === 'no-speech') {
                this.updateSpeechDisplay('لم أسمع أي شيء...');
                if (this.isAlwaysListening) {
                    setTimeout(() => this.startContinuousListening(), 500);
                } else {
                    this.speak('لم أسمع أي شيء، جرب مرة أخرى', 0.85);
                }
            } else if (event.error === 'not-allowed') {
                this.updateSpeechDisplay('الرجاء السماح بالوصول إلى الميكروفون');
                this.speak('الرجاء السماح بالوصول إلى الميكروفون', 0.85);
            } else if (event.error === 'network') {
                this.updateSpeechDisplay('مشكلة في الاتصال...');
                this.speak('مشكلة في الاتصال، جرب مرة أخرى', 0.85);
            } else if (event.error === 'aborted') {
                // تم الإيقاف عمداً - لا نعرض رسالة خطأ
                return;
            } else {
                this.updateSpeechDisplay('حدث خطأ، جرب مرة أخرى');
                this.speak('حدث خطأ، جرب مرة أخرى', 0.85);
            }
        };

        this.recognition.onend = () => {
            this.isListening = false;
            
            // إذا كان في وضع الاستماع المستمر ولم يتم اكتشاف كلمة التنبيه، نعيد التشغيل
            if (this.isAlwaysListening && !this.wakeWordDetected) {
                this.updateUI('waiting');
                setTimeout(() => {
                    if (this.isAlwaysListening && !this.wakeWordDetected) {
                        try {
                            this.startContinuousListening();
                        } catch (e) {
                            console.warn('Error restarting continuous listening:', e);
                        }
                    }
                }, 500);
            } else {
                this.updateUI(this.isAlwaysListening ? 'waiting' : 'idle');
            }
        };
    }

    initContinuousListening() {
        if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
            return;
        }

        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        this.continuousRecognition = new SpeechRecognition();
        
        // تحسين إعدادات اللغة العربية للاستماع المستمر
        const arabicLangs = ['ar-SA', 'ar-EG', 'ar-AE', 'ar-IQ', 'ar'];
        let langSet = false;
        for (const lang of arabicLangs) {
            try {
                this.continuousRecognition.lang = lang;
                langSet = true;
                console.log('Set continuous recognition language to:', lang);
                break;
            } catch (e) {
                continue;
            }
        }
        if (!langSet) {
            this.continuousRecognition.lang = 'en-US';
        }
        
        this.continuousRecognition.continuous = true;
        this.continuousRecognition.interimResults = true; // مهم جداً لرؤية النص أثناء الكلام
        this.continuousRecognition.maxAlternatives = 10;

        this.continuousRecognition.onresult = (event) => {
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const result = event.results[i];
                const transcript = result[0].transcript.trim().toLowerCase();
                const normalized = this.normalizeArabic(transcript);
                
                // Update speech display with what is being heard
                if (!result.isFinal) {
                    this.updateSpeechDisplay(transcript || 'جاري الاستماع...', true);
                }
                
                const wakeWordPatterns = [
                    this.wakeWord.toLowerCase(),
                    'نعم',
                    'نع',
                    'نعمه',
                    'نعمه',
                    'yes',
                    'ايوه',
                    'ايه',
                    'نعم',
                ];
                
                const hasWakeWord = wakeWordPatterns.some(pattern => {
                    const patternNormalized = this.normalizeArabic(pattern);
                    return normalized.includes(patternNormalized) || 
                           transcript.includes(pattern) ||
                           normalized.startsWith(patternNormalized) ||
                           transcript.startsWith(pattern);
                });
                
                if (hasWakeWord && !this.wakeWordDetected && result.isFinal) {
                    this.wakeWordDetected = true;
                    this.continuousRecognition.stop();
                    
                    this.updateUI('wake-word');
                    this.updateSpeechDisplay('نعم');
                    
                    // فقط نقول "نعم" بدون أي كلام إضافي
                    this.speak('نعم', 0.85);
                    
                    // بدء الاستماع للأمر مباشرة بعد قول "نعم"
                    setTimeout(() => {
                        this.updateUI('listening');
                        this.updateSpeechDisplay('جاري الاستماع...', true);
                        try {
                            this.recognition.start();
                        } catch (e) {
                            this.recognition.stop();
                            setTimeout(() => this.recognition.start(), 100);
                        }
                    }, 300); // تقليل التأخير للاستجابة السريعة
                    
                    return;
                }
            }
        };

        this.continuousRecognition.onerror = (event) => {
            console.log('Continuous recognition error:', event.error);
            
            if (event.error === 'no-speech') {
                // لا يوجد كلام - نستمر في الاستماع
                if (this.isAlwaysListening && !this.wakeWordDetected) {
                    setTimeout(() => {
                        try {
                            this.startContinuousListening();
                        } catch (e) {
                            console.warn('Error restarting after no-speech:', e);
                        }
                    }, 500);
                }
            } else if (event.error === 'aborted') {
                // تم الإيقاف عمداً
                return;
            } else if (event.error === 'not-allowed') {
                this.updateSpeechDisplay('الرجاء السماح بالوصول إلى الميكروفون');
                this.speak('الرجاء السماح بالوصول إلى الميكروفون', 0.85);
            } else {
                // أخطاء أخرى - نعيد المحاولة
                if (this.isAlwaysListening && !this.wakeWordDetected) {
                    setTimeout(() => {
                        try {
                            this.startContinuousListening();
                        } catch (e) {
                            console.warn('Error restarting after error:', e);
                        }
                    }, 1000);
                }
            }
        };

        this.continuousRecognition.onend = () => {
            if (this.isAlwaysListening && !this.wakeWordDetected) {
                setTimeout(() => this.startContinuousListening(), 300);
            }
        };
    }

    normalizeArabic(text) {
        return text
            .replace(/[إأآا]/g, 'ا')
            .replace(/ة/g, 'ه')
            .replace(/ى/g, 'ي')
            .replace(/[ًٌٍَُِّْ]/g, '')
            .replace(/\s+/g, ' ')
            .toLowerCase()
            .trim();
    }

    startContinuousListening() {
        if (!this.continuousRecognition) return;
        
        // إذا كان يعمل بالفعل، لا نعيد التشغيل
        if (this.isAlwaysListening) {
            try {
                // التحقق من أنه متوقف قبل إعادة التشغيل
                this.continuousRecognition.stop();
                setTimeout(() => {
                    try {
                        this.continuousRecognition.start();
                    } catch (e) {
                        console.warn('Error restarting continuous listening:', e);
                    }
                }, 300);
            } catch (e) {
                // قد يكون متوقفاً بالفعل
            }
            return;
        }
        
        this.isAlwaysListening = true;
        this.wakeWordDetected = false;
        
        // التأكد من إيقاف أي استماع سابق
        try {
            this.continuousRecognition.stop();
        } catch (e) {
            // قد يكون متوقفاً بالفعل
        }
        
        // بدء الاستماع المستمر بعد تأخير قصير
        setTimeout(() => {
            try {
                this.continuousRecognition.start();
                this.updateUI('waiting');
                this.startVisualizer();
                this.updateSpeechDisplay('قل "نعم" ثم الأمر المطلوب');
                console.log('Always-listening mode activated. Say "نعم" then your command.');
            } catch (e) {
                console.warn('Error starting continuous listening, retrying:', e);
                setTimeout(() => {
                    try {
                        this.continuousRecognition.start();
                        this.isAlwaysListening = true;
                        this.updateUI('waiting');
                        this.startVisualizer();
                        this.updateSpeechDisplay('قل "نعم" ثم الأمر المطلوب');
                    } catch (e2) {
                        console.error('Failed to start continuous listening:', e2);
                        this.isAlwaysListening = false;
                        this.updateSpeechDisplay('فشل في بدء الاستماع');
                    }
                }, 500);
            }
        }, 200);
    }

    stopContinuousListening() {
        this.isAlwaysListening = false;
        this.wakeWordDetected = false;
        
        if (this.continuousRecognition) {
            try {
                this.continuousRecognition.stop();
            } catch (e) {}
        }
        
        this.updateUI('idle');
    }

    startListening() {
        if (!this.recognition) {
            this.speak('المساعد الصوتي غير مدعوم في هذا المتصفح', 0.85);
            return;
        }

        if (this.isListening) {
            this.stopListening();
            return;
        }

        try {
            // التأكد من إيقاف أي استماع سابق
            try {
                this.recognition.stop();
            } catch (e) {
                // قد يكون متوقفاً بالفعل
            }
            
            // بدء الاستماع بعد تأخير قصير
            setTimeout(() => {
                try {
                    this.recognition.start();
                } catch (e) {
                    console.error('Error starting recognition:', e);
                    // المحاولة مرة أخرى بعد تأخير
                    setTimeout(() => {
                        try {
                            this.recognition.start();
                        } catch (e2) {
                            this.speak('حدث خطأ في بدء الاستماع، جرب مرة أخرى', 0.85);
                        }
                    }, 500);
                }
            }, 100);
        } catch (e) {
            console.error('Error starting recognition:', e);
            this.speak('حدث خطأ في بدء الاستماع', 0.85);
        }
    }

    stopListening() {
        if (this.recognition && this.isListening) {
            this.recognition.stop();
        }
    }

    speak(text, pitch = 1.2, rate = 0.95) {
        if (!this.synthesis) return;

        this.synthesis.cancel();
        this.isSpeaking = true;
        this.speechVolumeLevel = 0.5;

        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'ar-SA';
        utterance.rate = rate;
        utterance.pitch = pitch;
        utterance.volume = 1.0;

        // Animate speech visualization
        const speechInterval = setInterval(() => {
            this.speechVolumeLevel = 0.3 + Math.random() * 0.5;
        }, 100);

        utterance.onend = () => {
            this.isSpeaking = false;
            this.speechVolumeLevel = 0;
            clearInterval(speechInterval);
        };

        utterance.onerror = () => {
            this.isSpeaking = false;
            this.speechVolumeLevel = 0;
            clearInterval(speechInterval);
        };

        let voices = this.synthesis.getVoices();
        
        const setVoiceAndSpeak = () => {
            const arabicFemaleVoice = voices.find(voice => 
                (voice.lang.startsWith('ar') || voice.lang.includes('Arabic') || voice.lang.includes('ar-SA')) && 
                (voice.name.toLowerCase().includes('female') || 
                 voice.name.toLowerCase().includes('zira') ||
                 voice.name.toLowerCase().includes('hazel') ||
                 voice.name.toLowerCase().includes('samantha') ||
                 voice.name.toLowerCase().includes('zeina') ||
                 voice.name.toLowerCase().includes('salma') ||
                 voice.name.toLowerCase().includes('naomi') ||
                 voice.name.toLowerCase().includes('laila') ||
                 voice.gender === 'female')
            );
            
            if (arabicFemaleVoice) {
                utterance.voice = arabicFemaleVoice;
                utterance.pitch = Math.max(1.0, pitch - 0.1);
            } else {
                const arabicVoice = voices.find(voice => 
                    voice.lang.startsWith('ar') || 
                    voice.lang.includes('Arabic') ||
                    voice.lang.includes('ar-SA') ||
                    voice.lang.includes('ar-EG')
                );
                if (arabicVoice) {
                    utterance.voice = arabicVoice;
                }
                utterance.pitch = pitch;
            }
            
            this.synthesis.speak(utterance);
        };
        
        if (voices.length === 0) {
            this.synthesis.onvoiceschanged = () => {
                voices = this.synthesis.getVoices();
                setVoiceAndSpeak();
            };
            setTimeout(() => {
                voices = this.synthesis.getVoices();
                if (voices.length > 0) {
                    setVoiceAndSpeak();
                } else {
                    utterance.pitch = pitch;
                    this.synthesis.speak(utterance);
                }
            }, 100);
        } else {
            setVoiceAndSpeak();
        }
    }

    processCommand(command) {
        this.wakeWordDetected = false;
        let cmd = this.normalizeArabic(command.trim());
        
        // Remove wake word
        cmd = cmd.replace(new RegExp(this.wakeWord, 'gi'), '').trim();
        cmd = cmd.replace(/نعم/gi, '').trim();
        cmd = cmd.replace(/نع/gi, '').trim();
        cmd = cmd.replace(/نعمه/gi, '').trim();
        cmd = cmd.replace(/ايوه/gi, '').trim();
        cmd = cmd.replace(/ايه/gi, '').trim();
        cmd = cmd.replace(/yes/gi, '').trim();
        
        // Remove common filler words
        cmd = cmd.replace(/\b(و|في|على|من|إلى|عن|مع|ضد|بين|خلال|داخل|خارج|هذا|هذه|ذلك|تلك|ال|ل|ب|ك)\b/g, ' ').trim();
        
        const restartListening = () => {
            if (this.isAlwaysListening) {
                setTimeout(() => this.startContinuousListening(), 1000);
            }
        };

        // Navigation commands - Enhanced with multiple variations
        if (this.matchCommand(cmd, [
            'الرئيسية', 'الصفحة الرئيسية', 'البداية', 'الرئيسي', 'dashboard', 
            'الواجهة', 'الواجهة الرئيسية', 'البيت', 'البيت الرئيسي', 'المنزل',
            'الرئيسيه', 'الرئيسي', 'رئيسي', 'رئيسية', 'رئيسيه',
            'الواجهه', 'واجهة', 'واجهه', 'الواجهه الرئيسيه',
            'البيت الرئيسي', 'بيت', 'المنزل', 'منزل',
            'البدايه', 'بداية', 'بدايه', 'البدايه',
            'الصفحة الرئيسيه', 'صفحه رئيسيه', 'صفحة رئيسية'
        ])) {
            this.navigate('/');
            this.speak('جاري الانتقال إلى الصفحة الرئيسية', 0.85);
            restartListening();
            return;
        }
        else if (this.matchCommand(cmd, [
            'الطلبات', 'طلب', 'الفواتير', 'طلبات', 'فواتير', 'orders', 
            'الطلب', 'الفواتير', 'الطلبات', 'طلبات', 'طلب',
            'فواتير', 'فاتورة', 'الفاتورة', 'فواتير', 'فاتوره',
            'الطلبات', 'طلبات', 'الطلب', 'طلب', 'طلبات',
            'اوردر', 'اوردرات', 'الاوردر', 'الاوردرات',
            'order', 'orders', 'invoice', 'invoices'
        ])) {
            this.navigate('/orders');
            this.speak('جاري فتح صفحة الطلبات', 0.85);
            restartListening();
            return;
        }
        else if (this.matchCommand(cmd, [
            'الزبائن', 'زبون', 'العملاء', 'زبائن', 'عملاء', 'customers',
            'الزبون', 'العميل', 'زبائن', 'زبون', 'الزبائن',
            'عملاء', 'عميل', 'العملاء', 'العميل',
            'الزبائن', 'زبائن', 'زبون', 'الزبون',
            'كلاينت', 'كلاينتس', 'الكلينت', 'الكلينتس',
            'customer', 'customers', 'client', 'clients'
        ])) {
            this.navigate('/customers');
            this.speak('جاري فتح صفحة الزبائن', 0.85);
            restartListening();
            return;
        }
        else if (this.matchCommand(cmd, [
            'المخزون', 'منتج', 'المنتجات', 'مخزون', 'منتجات', 'inventory', 
            'stock', 'المخزن', 'المخازن', 'مخازن', 'مخزن',
            'المنتجات', 'منتجات', 'منتج', 'المنتج',
            'المخزون', 'مخزون', 'المخزن', 'مخزن',
            'ستوك', 'الستوك', 'انفنتوري', 'الانفنتوري',
            'product', 'products', 'stock', 'inventory'
        ])) {
            this.navigate('/inventory');
            this.speak('جاري فتح صفحة المخزون', 0.85);
            restartListening();
            return;
        }
        else if (this.matchCommand(cmd, [
            'الشحن', 'شركة النقل', 'شركات النقل', 'نقل', 'shipping', 
            'delivery', 'التوصيل', 'الشحنات', 'شحنات', 'شحنة',
            'النقل', 'نقل', 'شركة النقل', 'شركات النقل',
            'التوصيل', 'توصيل', 'الشحنات', 'شحنات',
            'شيبنج', 'الشيبنج', 'دليفري', 'الدليفري',
            'shipping', 'delivery', 'transport', 'transportation'
        ])) {
            this.navigate('/shipping');
            this.speak('جاري فتح صفحة الشحن', 0.85);
            restartListening();
            return;
        }
        else if (this.matchCommand(cmd, [
            'التقارير', 'تقرير', 'كشف', 'تقارير', 'reports', 
            'كشوفات', 'التقرير', 'كشوف', 'كشف', 'التقارير',
            'تقرير', 'التقرير', 'تقارير', 'التقارير',
            'كشف', 'الكشف', 'كشوف', 'كشوفات',
            'ريبورت', 'الريبورت', 'ريبورتس', 'الريبورتس',
            'report', 'reports', 'statement', 'statements'
        ])) {
            this.navigate('/reports');
            this.speak('جاري فتح صفحة التقارير', 0.85);
            restartListening();
            return;
        }
        else if (this.matchCommand(cmd, [
            'نقطة البيع', 'بيع', 'pos', 'point of sale', 'كاشير', 
            'البيع', 'نقطة بيع', 'نقطه بيع', 'نقطة البيع',
            'كاشير', 'الكاشير', 'كاشير', 'كاشير',
            'بيع', 'البيع', 'نقطة البيع', 'نقطه البيع',
            'بوس', 'البوس', 'بوينت اوف سيل',
            'pos', 'point of sale', 'cashier', 'cash register'
        ])) {
            this.navigate('/pos');
            this.speak('جاري فتح نقطة البيع', 0.85);
            restartListening();
            return;
        }
        else if (this.matchCommand(cmd, [
            'الموظفين', 'موظف', 'موظفين', 'employees', 
            'staff', 'الموظف', 'العاملين', 'عاملين', 'عامل',
            'الموظفين', 'موظفين', 'موظف', 'الموظف',
            'العاملين', 'عاملين', 'عامل', 'العامل',
            'امبلاي', 'الامبلاي', 'امبلايس', 'الامبلايس',
            'employee', 'employees', 'staff', 'worker', 'workers'
        ])) {
            this.navigate('/employees');
            this.speak('جاري فتح صفحة الموظفين', 0.85);
            restartListening();
            return;
        }
        else if (this.matchCommand(cmd, [
            'الموردين', 'مورد', 'موردين', 'suppliers', 
            'المورد', 'الموردون', 'موردون', 'مورد',
            'الموردين', 'موردين', 'مورد', 'المورد',
            'سابلاير', 'السابلاير', 'سابلايرز', 'السابلايرز',
            'supplier', 'suppliers', 'vendor', 'vendors'
        ])) {
            this.navigate('/suppliers');
            this.speak('جاري فتح صفحة الموردين', 0.85);
            restartListening();
            return;
        }
        else if (this.matchCommand(cmd, [
            'المصاريف', 'مصروف', 'مصاريف', 'expenses', 
            'المصروف', 'المصروفات', 'مصروفات', 'مصروف',
            'المصاريف', 'مصاريف', 'مصروف', 'المصروف',
            'اكسبنس', 'الاكسبنس', 'اكسبنسز', 'الاكسبنسز',
            'expense', 'expenses', 'cost', 'costs', 'spending'
        ])) {
            this.navigate('/expenses');
            this.speak('جاري فتح صفحة المصاريف', 0.85);
            restartListening();
            return;
        }
        else if (this.matchCommand(cmd, [
            'الحسابات', 'حساب', 'حسابات', 'accounts', 
            'الحساب', 'حسابات', 'حساب', 'الحساب',
            'اكاونت', 'الاكاونت', 'اكاونتس', 'الاكاونتس',
            'account', 'accounts', 'accounting', 'finance', 'financial'
        ])) {
            this.navigate('/accounts');
            this.speak('جاري فتح صفحة الحسابات', 0.85);
            restartListening();
            return;
        }
        
        // Search commands - Enhanced with multiple variations
        else if (this.matchCommand(cmd, [
            'ابحث', 'بحث', 'دور', 'دور عن', 'ابحث عن', 'ابحث في', 'ابحث على',
            'البحث', 'بحث عن', 'دور على', 'دور في', 'ابحث على',
            'شوف', 'شوف عن', 'شوف في', 'شوف على', 'اعرض', 'اعرض عن',
            'شوف لي', 'دور لي', 'ابحث لي', 'اعرض لي',
            'search', 'find', 'look', 'look for', 'look up', 'show', 'show me'
        ])) {
            const searchTerm = this.extractSearchTerm(cmd);
            if (searchTerm) {
                this.performSearch(searchTerm);
                this.speak(`جاري البحث عن ${searchTerm}`, 0.85);
            } else {
                this.speak('ما الذي تريد البحث عنه؟', 0.85);
            }
            restartListening();
            return;
        }
        
        // Order query commands - Ask about order details
        else if (this.matchCommand(cmd, [
            'اسئل', 'اسأل', 'سؤال', 'سئل', 'اعرف', 'أعرف', 'عرفني', 
            'شوف', 'شوف طلب', 'تفاصيل طلب', 'طلب رقم',
            'اسئل عن', 'اسأل عن', 'اعرف عن', 'عرفني عن',
            'شوف طلب', 'شوف الفاتورة', 'شوف الطلب', 'شوف الفاتورة',
            'تفاصيل', 'التفاصيل', 'تفاصيل الطلب', 'تفاصيل الفاتورة',
            'اعرف طلب', 'عرفني طلب', 'اعرف الفاتورة', 'عرفني الفاتورة',
            'ask', 'ask about', 'tell me', 'show me', 'details', 'order details'
        ])) {
            const orderId = this.extractNumber(cmd);
            if (orderId) {
                this.queryOrderDetails(orderId, cmd);
                restartListening();
                return;
            } else {
                this.speak('ما رقم الطلب الذي تريد السؤال عنه؟', 0.85);
                restartListening();
                return;
            }
        }
        
        // Order commands - Comprehensive Enhanced
        else if (this.currentPage.includes('/orders')) {
            if (this.matchCommand(cmd, ['تسديد', 'سدد', 'pay', 'settle', 'دفع', 'ادفع', 'سدد الطلب'])) {
                const orderId = this.extractNumber(cmd);
                if (orderId) {
                    this.executeOrderAction(orderId, 'pay');
                    this.speak(`جاري تسديد الطلب رقم ${orderId}`, 0.85);
                } else {
                    this.speak('ما رقم الطلب الذي تريد تسديده؟', 0.85);
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, [
                'عرض', 'تفاصيل', 'تفاصيل الطلب', 'view', 'show', 'details', 
                'أعرض', 'عرض تفاصيل', 'شوف', 'شوف الطلب', 'شوف الفاتورة',
                'عرض الطلب', 'عرض الفاتورة', 'تفاصيل', 'التفاصيل',
                'شوف تفاصيل', 'اعرض تفاصيل', 'شوف الطلب', 'اعرض الطلب',
                'view', 'show', 'details', 'view order', 'show order', 'order details'
            ])) {
                const orderId = this.extractNumber(cmd);
                if (orderId) {
                    this.executeOrderAction(orderId, 'view');
                    this.speak(`جاري عرض تفاصيل الطلب رقم ${orderId}`, 0.85);
                } else {
                    this.speak('ما رقم الطلب الذي تريد عرضه؟', 0.85);
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, [
                'طباعة', 'اطبع', 'print', 'طبع', 'اطبع الفاتورة',
                'طباعة الفاتورة', 'اطبع الفاتورة', 'طبع الفاتورة',
                'طباعة الطلب', 'اطبع الطلب', 'طبع الطلب',
                'طباعة', 'اطبع', 'طبع', 'طباعه', 'اطبعه',
                'print', 'print invoice', 'print order', 'print receipt'
            ])) {
                const orderId = this.extractNumber(cmd);
                if (orderId) {
                    this.executeOrderAction(orderId, 'print');
                    this.speak(`جاري طباعة الفاتورة رقم ${orderId}`, 0.85);
                } else if (this.matchCommand(cmd, ['المحدد', 'المحددة', 'selected', 'المختار'])) {
                    if (typeof printSelectedInvoices === 'function') {
                        printSelectedInvoices();
                        this.speak('جاري طباعة الفواتير المحددة', 0.85);
                    }
                } else if (this.matchCommand(cmd, ['كشف', 'الكشف', 'report', 'كشف المحدد'])) {
                    if (typeof printSelectedReport === 'function') {
                        printSelectedReport();
                        this.speak('جاري طباعة الكشف', 0.85);
                    }
                } else {
                    this.speak('ما رقم الفاتورة التي تريد طباعتها؟', 0.85);
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['إلغاء', 'ألغ', 'cancel', 'delete', 'حذف', 'ألغ الطلب', 'احذف'])) {
                const orderId = this.extractNumber(cmd);
                if (orderId) {
                    if (typeof cancelOrder === 'function') {
                        if (confirm(`هل تريد إلغاء الطلب رقم ${orderId}؟`)) {
                            cancelOrder(orderId);
                            this.speak(`جاري إلغاء الطلب رقم ${orderId}`, 0.85);
                        }
                    }
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['مرتجع', 'ارجع', 'return', 'رجع', 'مرتجع الطلب'])) {
                const orderId = this.extractNumber(cmd);
                if (orderId) {
                    if (typeof markAsReturned === 'function') {
                        markAsReturned(orderId);
                        this.speak(`جاري تحديد الطلب رقم ${orderId} كمرتجع`, 0.85);
                    }
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['تحديد الكل', 'select all', 'حدد كل', 'اختر الكل', 'حدد الجميع', 'تحديد جميع'])) {
                if (typeof toggleAll === 'function') {
                    const checkbox = document.querySelector('input[type="checkbox"][onchange*="toggleAll"], input[type="checkbox"][onclick*="toggleAll"]');
                    if (checkbox) {
                        checkbox.checked = true;
                        checkbox.dispatchEvent(new Event('change'));
                        checkbox.dispatchEvent(new Event('click'));
                    }
                    this.speak('تم تحديد جميع الطلبات', 0.85);
                } else if (typeof selectAll === 'function') {
                    selectAll();
                    this.speak('تم تحديد جميع الطلبات', 0.85);
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['إلغاء التحديد', 'clear selection', 'ألغ التحديد', 'امسح التحديد', 'إلغاء الكل'])) {
                const checkboxes = document.querySelectorAll('input[type="checkbox"].row, input[type="checkbox"][class*="row"]');
                checkboxes.forEach(cb => cb.checked = false);
                const selectAllCheckbox = document.querySelector('input[type="checkbox"][onchange*="toggleAll"], input[type="checkbox"][onclick*="toggleAll"]');
                if (selectAllCheckbox) selectAllCheckbox.checked = false;
                this.speak('تم إلغاء تحديد جميع الطلبات', 0.85);
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['طباعة المحدد', 'print selected', 'اطبع المحدد', 'طبع المحدد', 'اطبع الفواتير المحددة'])) {
                if (typeof printSelectedInvoices === 'function') {
                    printSelectedInvoices();
                    this.speak('جاري طباعة الفواتير المحددة', 0.85);
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['كشف المحدد', 'طباعة الكشف', 'print report', 'كشف', 'اطبع الكشف'])) {
                if (typeof printSelectedReport === 'function') {
                    printSelectedReport();
                    this.speak('جاري طباعة الكشف', 0.85);
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['حفظ الكشف', 'save report', 'احفظ الكشف', 'احفظ'])) {
                if (typeof saveReport === 'function') {
                    saveReport();
                    this.speak('جاري حفظ الكشف', 0.85);
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['Excel', 'تصدير', 'export', 'اكسل', 'تصدير Excel'])) {
                if (typeof exportExcel === 'function') {
                    exportExcel();
                    this.speak('جاري تصدير البيانات إلى Excel', 0.85);
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['إعادة تعيين', 'clear filters', 'مسح الفلاتر', 'امسح', 'إعادة'])) {
                if (typeof clearFilters === 'function') {
                    clearFilters();
                    this.speak('تم إعادة تعيين الفلاتر', 0.85);
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['فلتر', 'filter', 'تصفية', 'فلتر حسب'])) {
                if (this.matchCommand(cmd, ['تم الطلب', 'طلبات جديدة'])) {
                    if (typeof filterByStatus === 'function') {
                        filterByStatus('تم الطلب');
                        this.speak('تم تطبيق فلتر تم الطلب', 0.85);
                    }
                } else if (this.matchCommand(cmd, ['جاري الشحن', 'شحن'])) {
                    if (typeof filterByStatus === 'function') {
                        filterByStatus('جاري الشحن');
                        this.speak('تم تطبيق فلتر جاري الشحن', 0.85);
                    }
                } else if (this.matchCommand(cmd, ['تم التوصيل', 'توصيل'])) {
                    if (typeof filterByStatus === 'function') {
                        filterByStatus('تم التوصيل');
                        this.speak('تم تطبيق فلتر تم التوصيل', 0.85);
                    }
                } else if (this.matchCommand(cmd, ['مسدد', 'مدفوع'])) {
                    if (typeof filterByStatus === 'function') {
                        filterByStatus('مسدد');
                        this.speak('تم تطبيق فلتر مسدد', 0.85);
                    }
                } else if (this.matchCommand(cmd, ['راجع', 'مرتجع'])) {
                    if (typeof filterByStatus === 'function') {
                        filterByStatus('راجع');
                        this.speak('تم تطبيق فلتر راجع', 0.85);
                    }
                } else if (this.matchCommand(cmd, ['غير مسدد', 'غير مدفوع'])) {
                    if (typeof filterByPayment === 'function') {
                        filterByPayment('غير مسدد');
                        this.speak('تم تطبيق فلتر غير مسدد', 0.85);
                    }
                } else {
                    this.speak('أخبرني نوع التصفية التي تريدها', 0.85);
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['تغيير الحالة', 'غير الحالة', 'change status'])) {
                const status = this.extractAfterKeyword(cmd, ['حالة', 'status']);
                const orderId = this.extractNumber(cmd);
                if (orderId && status) {
                    // Execute status change
                    this.speak(`جاري تغيير حالة الطلب رقم ${orderId}`, 0.85);
                } else {
                    this.speak('ما رقم الطلب والحالة الجديدة؟', 0.85);
                }
                restartListening();
                return;
            }
        }
        
        // POS commands - Enhanced
        else if (this.currentPage.includes('/pos')) {
            if (this.matchCommand(cmd, ['إضافة منتج', 'أضف منتج', 'add product', 'منتج', 'اضف منتج', 'ضيف منتج'])) {
                const productName = this.extractAfterKeyword(cmd, ['منتج', 'إضافة', 'add', 'اضف', 'ضيف']);
                if (productName) {
                    this.searchAndAddProduct(productName);
                    this.speak(`جاري البحث عن المنتج ${productName}`, 0.85);
                } else {
                    this.speak('ما اسم المنتج الذي تريد إضافته؟', 0.85);
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['حفظ', 'احفظ الطلب', 'أكمل الطلب', 'save', 'submit', 'complete', 'احفظ', 'اكمل', 'انهي'])) {
                this.submitPOSOrder();
                this.speak('جاري حفظ الطلب', 0.85);
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['كاميرا', 'افتح الكاميرا', 'مسح', 'camera', 'scan', 'الكاميرا', 'افتح كاميرا'])) {
                this.openPOSCamera();
                this.speak('جاري فتح الكاميرا', 0.85);
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['إضافة زبون', 'زبون جديد', 'add customer', 'اضف زبون', 'عميل جديد', 'زبون'])) {
                if (typeof openAdd === 'function') {
                    openAdd();
                    this.speak('جاري فتح نموذج إضافة زبون', 0.85);
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['مسح الكل', 'clear', 'مسح', 'امسح', 'احذف الكل', 'امسح الكل'])) {
                if (typeof items !== 'undefined' && Array.isArray(items)) {
                    items.length = 0;
                    if (typeof renderItems === 'function') renderItems();
                    this.speak('تم مسح جميع المنتجات', 0.85);
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['حذف منتج', 'احذف', 'delete product', 'شيل منتج'])) {
                const productName = this.extractAfterKeyword(cmd, ['منتج', 'حذف', 'delete', 'شيل']);
                if (productName && typeof items !== 'undefined') {
                    const index = items.findIndex(i => i.name && i.name.includes(productName));
                    if (index !== -1) {
                        items.splice(index, 1);
                        if (typeof renderItems === 'function') renderItems();
                        this.speak(`تم حذف المنتج ${productName}`, 0.85);
                    }
                }
                restartListening();
                return;
            }
        }
        
        // Inventory commands
        else if (this.currentPage.includes('/inventory')) {
            if (this.matchCommand(cmd, ['إضافة منتج', 'منتج جديد', 'add product', 'new product', 'اضف منتج'])) {
                this.openAddProductModal();
                this.speak('جاري فتح نموذج إضافة منتج جديد', 0.85);
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['بحث منتج', 'ابحث عن منتج', 'search product'])) {
                const productName = this.extractSearchTerm(cmd);
                if (productName) {
                    this.performSearch(productName);
                    this.speak(`جاري البحث عن ${productName}`, 0.85);
                }
                restartListening();
                return;
            }
        }
        
        // Customer commands
        else if (this.currentPage.includes('/customers')) {
            if (this.matchCommand(cmd, ['إضافة زبون', 'زبون جديد', 'عميل جديد', 'add customer', 'اضف زبون'])) {
                this.openAddCustomerModal();
                this.speak('جاري فتح نموذج إضافة زبون جديد', 0.85);
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['بحث زبون', 'ابحث عن زبون', 'search customer'])) {
                const customerName = this.extractSearchTerm(cmd);
                if (customerName) {
                    this.performSearch(customerName);
                    this.speak(`جاري البحث عن ${customerName}`, 0.85);
                }
                restartListening();
                return;
            }
        }
        
        // Shipping commands
        else if (this.currentPage.includes('/shipping')) {
            if (this.matchCommand(cmd, ['تسديد', 'سدد', 'settle', 'سدد الطلب'])) {
                const orderId = this.extractNumber(cmd);
                if (orderId) {
                    if (typeof settle === 'function') {
                        settle(orderId);
                        this.speak(`جاري تسديد الطلب رقم ${orderId}`, 0.85);
                    }
                }
                restartListening();
                return;
            }
            else if (this.matchCommand(cmd, ['ترجيع', 'ارجع', 'return', 'ارجع الطلب'])) {
                const orderId = this.extractNumber(cmd);
                if (orderId) {
                    if (typeof returnOrder === 'function') {
                        returnOrder(orderId);
                        this.speak(`جاري ترجيع الطلب رقم ${orderId}`, 0.85);
                    }
                }
                restartListening();
                return;
            }
        }
        
        // Quick invoice search
        else if (this.isInvoiceNumber(cmd) && !this.matchCommand(cmd, ['تسديد', 'عرض', 'طباعة', 'إلغاء'])) {
            const invoiceNum = this.extractNumber(cmd);
            if (invoiceNum) {
                this.searchInvoice(invoiceNum);
                this.speak(`جاري البحث عن الفاتورة رقم ${invoiceNum}`, 0.85);
                restartListening();
                return;
            }
        }
        
        // General commands - Enhanced
        else if (this.matchCommand(cmd, ['تحديث', 'حدث', 'تحديث الصفحة', 'refresh', 'reload', 'حدث الصفحة', 'حدثي'])) {
            location.reload();
            this.speak('جاري تحديث الصفحة', 0.85);
            return;
        }
        else if (this.matchCommand(cmd, ['رجوع', 'ارجع', 'الخلف', 'back', 'للخلف', 'رجع'])) {
            history.back();
            this.speak('جاري الرجوع للخلف', 0.85);
            restartListening();
            return;
        }
        else if (this.matchCommand(cmd, ['إغلاق', 'أغلق', 'close', 'exit', 'اخرج', 'اقفل'])) {
            this.speak('إلى اللقاء', 0.85);
            this.stopContinuousListening();
            return;
        }
        else if (this.matchCommand(cmd, ['تفعيل الاستماع', 'استمع دائماً', 'always listen', 'تفعيل', 'استمع', 'شغل الاستماع'])) {
            this.startContinuousListening();
            this.speak('تم تفعيل الاستماع المستمر، قل نعم ثم الأمر المطلوب', 0.85);
            return;
        }
        else if (this.matchCommand(cmd, ['إيقاف الاستماع', 'أوقف الاستماع', 'stop listening', 'إيقاف', 'أوقف', 'اطفي الاستماع'])) {
            this.stopContinuousListening();
            this.speak('تم إيقاف الاستماع المستمر', 0.85);
            return;
        }
        else if (this.matchCommand(cmd, ['مساعدة', 'مساعدة صوتية', 'الأوامر', 'help', 'commands', 'المساعدة', 'شوف الأوامر'])) {
            this.showHelp();
            restartListening();
            return;
        }
        else if (this.matchCommand(cmd, ['المبيعات', 'sales', 'total sales', 'إجمالي المبيعات', 'مبيعات'])) {
            this.showSalesInfo();
            restartListening();
            return;
        }
        else if (this.matchCommand(cmd, ['الربح', 'profit', 'today profit', 'ربح اليوم', 'ربح'])) {
            this.showProfitInfo();
            restartListening();
            return;
        }
        else {
            // Try to be more helpful with common mistakes
            if (cmd.includes('نعم') || cmd.includes('نع') || cmd.includes('ايوه')) {
                this.speak('أنا هنا، قل الأمر المطلوب بعد نعم. مثل: نعم الصفحة الرئيسية', 0.85);
            } else {
                this.speak('لم أفهم الأمر، قل نعم ثم الأمر المطلوب. أو قل مساعدة لرؤية الأوامر المتاحة', 0.85);
            }
            restartListening();
        }
    }

    matchCommand(cmd, keywords) {
        const normalizedCmd = this.normalizeArabic(cmd);
        
        return keywords.some(keyword => {
            const normalizedKeyword = this.normalizeArabic(keyword);
            
            // 1. مطابقة مباشرة كاملة
            if (normalizedCmd === normalizedKeyword || cmd === keyword) {
                return true;
            }
            
            // 2. مطابقة جزئية (الكلمة موجودة في الأمر)
            if (normalizedCmd.includes(normalizedKeyword) || cmd.includes(keyword)) {
                return true;
            }
            
            // 3. مطابقة الكلمات الفردية (للمصطلحات المركبة)
            const keywordWords = normalizedKeyword.split(/\s+/).filter(w => w.length > 1);
            const cmdWords = normalizedCmd.split(/\s+/).filter(w => w.length > 1);
            
            if (keywordWords.length > 1 && keywordWords.length <= 3) {
                // إذا كانت جميع كلمات الكلمة المفتاحية موجودة في الأمر
                const allWordsFound = keywordWords.every(kw => 
                    cmdWords.some(cw => {
                        // مطابقة كاملة أو جزئية
                        return cw === kw || cw.includes(kw) || kw.includes(cw);
                    })
                );
                if (allWordsFound) return true;
            }
            
            // 4. مطابقة جزئية ذكية (للكلمات الطويلة)
            if (normalizedKeyword.length > 4 && normalizedCmd.length > 4) {
                // إذا كانت 60% من الكلمة موجودة
                const minMatchLength = Math.max(3, Math.floor(normalizedKeyword.length * 0.6));
                
                for (let i = 0; i <= normalizedCmd.length - minMatchLength; i++) {
                    const substring = normalizedCmd.substring(i, i + minMatchLength);
                    if (normalizedKeyword.includes(substring)) {
                        return true;
                    }
                }
                
                // العكس: البحث عن جزء من الكلمة المفتاحية في الأمر
                for (let i = 0; i <= normalizedKeyword.length - minMatchLength; i++) {
                    const substring = normalizedKeyword.substring(i, i + minMatchLength);
                    if (normalizedCmd.includes(substring)) {
                        return true;
                    }
                }
            }
            
            // 5. مطابقة بدون التشكيل والهمزات (للمرونة)
            const cmdNoDiacritics = normalizedCmd.replace(/[ًٌٍَُِّْ]/g, '');
            const keywordNoDiacritics = normalizedKeyword.replace(/[ًٌٍَُِّْ]/g, '');
            if (cmdNoDiacritics.includes(keywordNoDiacritics) && keywordNoDiacritics.length > 2) {
                return true;
            }
            
            return false;
        });
    }

    extractNumber(text) {
        const patterns = [
            /\d+/,
            /[٠١٢٣٤٥٦٧٨٩]+/,
            /رقم\s*(\d+)/,
            /#\s*(\d+)/,
            /(\d+)/,
            /الطلب\s*(\d+)/,
            /فاتورة\s*(\d+)/,
        ];
        
        for (const pattern of patterns) {
            const match = text.match(pattern);
            if (match) {
                let num = match[1] || match[0];
                if (/[٠١٢٣٤٥٦٧٨٩]/.test(num)) {
                    const arabicDigits = '٠١٢٣٤٥٦٧٨٩';
                    const englishDigits = '0123456789';
                    num = num.split('').map(d => {
                        const idx = arabicDigits.indexOf(d);
                        return idx !== -1 ? englishDigits[idx] : d;
                    }).join('');
                }
                return parseInt(num);
            }
        }
        
        return null;
    }

    isInvoiceNumber(cmd) {
        const num = this.extractNumber(cmd);
        if (num && num > 0 && num < 100000) {
            const cleaned = cmd.replace(/\d+/g, '').replace(/[٠١٢٣٤٥٦٧٨٩]/g, '').trim();
            return cleaned.length < 5;
        }
        return false;
    }

    async searchInvoice(invoiceNumber) {
        try {
            if (this.currentPage.includes('/orders')) {
                const searchInputs = [
                    document.querySelector('input[type="search"]'),
                    document.querySelector('input[placeholder*="بحث"]'),
                    document.querySelector('input[id*="search"]'),
                    document.querySelector('input[name*="search"]'),
                    document.querySelector('#q'),
                    document.querySelector('#searchInput'),
                ].filter(Boolean);
                
                if (searchInputs.length > 0) {
                    const searchInput = searchInputs[0];
                    searchInput.value = invoiceNumber.toString();
                    searchInput.focus();
                    
                    searchInput.dispatchEvent(new Event('input', { bubbles: true }));
                    searchInput.dispatchEvent(new Event('keyup', { bubbles: true }));
                    searchInput.dispatchEvent(new Event('change', { bubbles: true }));
                    
                    if (typeof search === 'function') {
                        setTimeout(() => search(), 100);
                    } else if (typeof applyFilters === 'function') {
                        setTimeout(() => applyFilters(), 100);
                    }
                    
                    this.showToast(`البحث عن الفاتورة رقم ${invoiceNumber}`, 'info');
                    this.speak(`تم البحث عن الفاتورة رقم ${invoiceNumber}`, 0.85);
                    return;
                }
            }
            
            const response = await fetch(`/api/index/search?q=${invoiceNumber}`);
            const results = await response.json();
            
            if (results && results.length > 0) {
                const invoice = results.find(r => r.id == invoiceNumber) || results[0];
                
                if (invoice.id == invoiceNumber) {
                    this.speak(`تم العثور على الفاتورة رقم ${invoice.id}`, 0.85);
                    this.showToast(`✅ الفاتورة رقم ${invoice.id} - ${invoice.customer || invoice.phone || '—'} - ${invoice.total} د.ع`, 'success');
                    
                    if (!this.currentPage.includes('/orders')) {
                        this.navigate('/orders');
                        setTimeout(() => {
                            this.searchInvoice(invoiceNumber);
                        }, 1000);
                    } else {
                        setTimeout(() => {
                            const rows = document.querySelectorAll('tr');
                            for (const row of rows) {
                                const firstCell = row.querySelector('td');
                                if (firstCell && firstCell.textContent.trim() == invoiceNumber.toString()) {
                                    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                    row.style.background = 'rgba(59, 130, 246, 0.4)';
                                    row.style.transition = 'background 0.3s';
                                    setTimeout(() => {
                                        row.style.background = '';
                                    }, 4000);
                                    break;
                                }
                            }
                        }, 500);
                    }
                } else {
                    this.speak(`تم العثور على ${results.length} نتيجة`, 0.85);
                    this.showToast(`تم العثور على ${results.length} نتيجة`, 'info');
                }
            } else {
                this.speak(`لم يتم العثور على فاتورة برقم ${invoiceNumber}`, 0.85);
                this.showToast(`❌ لم يتم العثور على فاتورة برقم ${invoiceNumber}`, 'warning');
            }
        } catch (error) {
            console.error('Error searching invoice:', error);
            this.speak('حدث خطأ أثناء البحث عن الفاتورة', 0.85);
            this.showToast('حدث خطأ أثناء البحث', 'error');
        }
    }

    extractSearchTerm(cmd) {
        const patterns = [
            /ابحث عن (.+)/,
            /بحث (.+)/,
            /ابحث (.+)/,
            /دور (.+)/,
            /دور عن (.+)/,
            /دور على (.+)/,
            /دور في (.+)/,
            /شوف (.+)/,
            /شوف عن (.+)/,
            /شوف في (.+)/,
            /اعرض (.+)/,
            /اعرض عن (.+)/,
            /البحث عن (.+)/,
            /search (.+)/i,
            /find (.+)/i,
            /look for (.+)/i,
            /look up (.+)/i,
        ];
        
        for (const pattern of patterns) {
            const match = cmd.match(pattern);
            if (match) return match[1].trim();
        }
        
        // إذا لم يجد نمط، يحاول استخراج الكلمات بعد كلمات البحث
        const searchKeywords = ['ابحث', 'بحث', 'دور', 'شوف', 'اعرض', 'search', 'find', 'look'];
        for (const keyword of searchKeywords) {
            if (cmd.includes(keyword)) {
                const index = cmd.indexOf(keyword);
                const afterKeyword = cmd.substring(index + keyword.length).trim();
                // إزالة كلمات إضافية مثل "عن" أو "في"
                const cleaned = afterKeyword.replace(/^(عن|في|على|ل|ب|من)\s+/i, '').trim();
                if (cleaned && cleaned.length > 0) {
                    return cleaned;
                }
            }
        }
        
        return null;
    }

    extractAfterKeyword(cmd, keywords) {
        for (const keyword of keywords) {
            const index = cmd.indexOf(keyword);
            if (index !== -1) {
                return cmd.substring(index + keyword.length).trim();
            }
        }
        return null;
    }

    navigate(path) {
        window.location.href = path;
    }

    performSearch(searchTerm) {
        const searchInput = document.querySelector('input[type="search"], input[placeholder*="بحث"], input[id*="search"], input[name*="search"], #q, #searchInput');
        if (searchInput) {
            searchInput.value = searchTerm;
            searchInput.dispatchEvent(new Event('input', { bubbles: true }));
            searchInput.dispatchEvent(new Event('keyup', { bubbles: true }));
            if (typeof applyFilters === 'function') {
                setTimeout(() => applyFilters(), 100);
            }
        } else {
            this.showToast(`البحث عن: ${searchTerm}`, 'info');
        }
    }

    executeOrderAction(orderId, action) {
        if (action === 'pay' && typeof pay === 'function') {
            pay(orderId);
        } else if (action === 'view' && typeof showDetails === 'function') {
            showDetails(orderId);
        } else if (action === 'print' && typeof printSingleInvoice === 'function') {
            printSingleInvoice(orderId);
        } else {
            this.showToast(`تنفيذ ${action} للطلب ${orderId}`, 'info');
        }
    }

    searchAndAddProduct(productName) {
        const searchInput = document.getElementById('searchProduct');
        if (searchInput) {
            searchInput.value = productName;
            searchInput.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }

    submitPOSOrder() {
        if (typeof submitOrder === 'function') {
            submitOrder();
        } else {
            const submitBtn = document.querySelector('button[onclick*="submit"], button:contains("حفظ")');
            if (submitBtn) submitBtn.click();
        }
    }

    openPOSCamera() {
        const cameraBtn = document.getElementById('cameraInput');
        if (cameraBtn) {
            cameraBtn.click();
        } else if (typeof openCamera === 'function') {
            openCamera();
        }
    }

    openAddProductModal() {
        const addBtn = document.querySelector('button:contains("إضافة"), button:contains("منتج جديد")');
        if (addBtn) addBtn.click();
        else if (typeof openAdd === 'function') openAdd();
    }

    openAddCustomerModal() {
        const addBtn = document.querySelector('button:contains("إضافة"), button:contains("زبون جديد")');
        if (addBtn) addBtn.click();
        else if (typeof openAdd === 'function') openAdd();
    }

    showHelp() {
        const helpText = `
            الأوامر المتاحة:
            
            التنقل:
            - "الصفحة الرئيسية"، "الطلبات"، "الزبائن"، "المخزون"، "الشحن"، "التقارير"، "نقطة البيع"
            
            صفحة الطلبات:
            - "تسديد الطلب [الرقم]"
            - "عرض الطلب [الرقم]"
            - "طباعة [الرقم]" أو "طباعة المحدد" أو "طباعة الكشف"
            - "مرتجع [الرقم]"
            - "تحديد الكل"، "إلغاء التحديد"
            - "فلتر تم الطلب" أو "فلتر مسدد" أو "فلتر غير مسدد"
            - "Excel" للتصدير
            - "إعادة تعيين" لمسح الفلاتر
            
            نقطة البيع:
            - "إضافة منتج [الاسم]"
            - "حفظ الطلب"
            - "كاميرا"
            - "مسح الكل"
            
            عامة:
            - "ابحث عن [الكلمة]"
            - "تحديث"، "رجوع"، "مساعدة"
            - "المبيعات"، "الربح"
        `;
        this.showToast(helpText, 'info');
        this.speak('مرحباً، أنا Finora مساعدك الذكي. يمكنك قول نعم ثم الأمر المطلوب. مثل: نعم الصفحة الرئيسية، نعم الطلبات، نعم البحث. قل مساعدة لمزيد من الأوامر', 0.85);
    }

    async showSalesInfo() {
        try {
            const response = await fetch('/api/index/reports');
            const data = await response.json();
            const sales = data.sales || 0;
            this.speak(`إجمالي المبيعات هو ${sales.toLocaleString()} دينار عراقي`, 0.85);
            this.showToast(`إجمالي المبيعات: ${sales.toLocaleString()} د.ع`, 'success');
        } catch (e) {
            this.speak('حدث خطأ في جلب معلومات المبيعات', 0.85);
        }
    }

    async showProfitInfo() {
        try {
            const response = await fetch('/api/index/today-profit');
            const data = await response.json();
            const profit = data.profit || 0;
            this.speak(`ربح اليوم هو ${profit.toLocaleString()} دينار عراقي`, 0.85);
            this.showToast(`ربح اليوم: ${profit.toLocaleString()} د.ع`, 'success');
        } catch (e) {
            this.speak('حدث خطأ في جلب معلومات الربح', 0.85);
        }
    }

    async queryOrderDetails(orderId, question) {
        try {
            const response = await fetch(`/orders/query/${orderId}`);
            const data = await response.json();
            
            if (!data.success || !data.order) {
                this.speak(`لم يتم العثور على طلب برقم ${orderId}`, 0.85);
                this.showToast(`❌ لم يتم العثور على طلب برقم ${orderId}`, 'warning');
                return;
            }
            
            const order = data.order;
            const q = this.normalizeArabic(question);
            
            // من مندوب / من الموظف
            if (this.matchCommand(q, ['مندوب', 'موظف', 'employee', 'الموظف', 'من مندوب', 'من موظف', 'مندوب مين', 'موظف مين'])) {
                const answer = `الطلب رقم ${orderId} من المندوب ${order.employee_name || 'غير محدد'}`;
                this.speak(answer, 0.85);
                this.showToast(`👤 ${answer}`, 'info');
                return;
            }
            
            // من الزبون / اسم الزبون
            if (this.matchCommand(q, ['زبون', 'عميل', 'customer', 'الزبون', 'اسم الزبون', 'من زبون', 'زبون مين', 'اسم العميل'])) {
                const answer = `الطلب رقم ${orderId} للزبون ${order.customer_name || 'غير محدد'}`;
                this.speak(answer, 0.85);
                this.showToast(`👤 ${answer}`, 'info');
                return;
            }
            
            // رقم الزبون / هاتف الزبون
            if (this.matchCommand(q, ['رقم', 'هاتف', 'phone', 'تلفون', 'رقم الزبون', 'هاتف الزبون', 'رقم الهاتف'])) {
                const phone = order.customer_phone || 'غير محدد';
                const answer = `رقم هاتف زبون الطلب ${orderId} هو ${phone}`;
                this.speak(answer, 0.85);
                this.showToast(`📞 ${answer}`, 'info');
                return;
            }
            
            // المبلغ / الإجمالي
            if (this.matchCommand(q, ['مبلغ', 'إجمالي', 'total', 'المبلغ', 'الإجمالي', 'كم المبلغ', 'كم الإجمالي', 'المبلغ كم'])) {
                const answer = `إجمالي الطلب رقم ${orderId} هو ${order.total.toLocaleString()} دينار عراقي`;
                this.speak(answer, 0.85);
                this.showToast(`💰 ${answer}`, 'success');
                return;
            }
            
            // الحالة / حالة الطلب
            if (this.matchCommand(q, ['حالة', 'status', 'الحالة', 'حالة الطلب', 'شلون الطلب', 'وين الطلب'])) {
                const answer = `حالة الطلب رقم ${orderId} هي ${order.status || 'غير محدد'} وحالة الدفع ${order.payment_status || 'غير محدد'}`;
                this.speak(answer, 0.85);
                this.showToast(`📋 ${answer}`, 'info');
                return;
            }
            
            // المحافظة / المدينة
            if (this.matchCommand(q, ['محافظة', 'مدينة', 'city', 'المحافظة', 'المدينة', 'وين', 'من وين'])) {
                const answer = `زبون الطلب ${orderId} من محافظة ${order.customer_city || 'غير محدد'}`;
                this.speak(answer, 0.85);
                this.showToast(`📍 ${answer}`, 'info');
                return;
            }
            
            // العنوان
            if (this.matchCommand(q, ['عنوان', 'address', 'العنوان', 'وين العنوان', 'عنوان الزبون'])) {
                const answer = `عنوان زبون الطلب ${orderId} هو ${order.customer_address || 'غير محدد'}`;
                this.speak(answer, 0.85);
                this.showToast(`📍 ${answer}`, 'info');
                return;
            }
            
            // المنتجات / الأصناف
            if (this.matchCommand(q, ['منتج', 'منتجات', 'أصناف', 'items', 'المنتجات', 'الأصناف', 'شلون المنتجات', 'كم منتج'])) {
                const itemsCount = order.items_count || 0;
                const itemsList = order.items ? order.items.map(i => `${i.name} (${i.quantity})`).join('، ') : 'لا توجد منتجات';
                const answer = `الطلب رقم ${orderId} يحتوي على ${itemsCount} منتج: ${itemsList}`;
                this.speak(answer, 0.85);
                this.showToast(`📦 ${answer}`, 'info');
                return;
            }
            
            // شركة النقل
            if (this.matchCommand(q, ['نقل', 'شحن', 'شركة', 'shipping', 'شركة النقل', 'من شركة نقل', 'شركة الشحن'])) {
                const shipping = order.shipping_company || 'غير محدد';
                const answer = `شركة النقل للطلب ${orderId} هي ${shipping}`;
                this.speak(answer, 0.85);
                this.showToast(`🚚 ${answer}`, 'info');
                return;
            }
            
            // التاريخ
            if (this.matchCommand(q, ['تاريخ', 'تاريخ الطلب', 'متى', 'date', 'متى الطلب', 'تاريخ الفاتورة'])) {
                const date = order.created_at || 'غير محدد';
                const answer = `تاريخ الطلب رقم ${orderId} هو ${date}`;
                this.speak(answer, 0.85);
                this.showToast(`📅 ${answer}`, 'info');
                return;
            }
            
            // تفاصيل عامة (إذا لم يحدد سؤال محدد)
            const summary = `الطلب رقم ${orderId}: الزبون ${order.customer_name}، المبلغ ${order.total.toLocaleString()} د.ع، الحالة ${order.status}، من المندوب ${order.employee_name}`;
            this.speak(summary, 0.85);
            this.showToast(`📋 ${summary}`, 'info');
            
        } catch (error) {
            console.error('Error querying order:', error);
            this.speak('حدث خطأ أثناء جلب تفاصيل الطلب', 0.85);
            this.showToast('❌ حدث خطأ أثناء جلب تفاصيل الطلب', 'error');
        }
    }

    updateUI(state) {
        const btn = document.getElementById('voiceAssistantBtn');
        if (!btn) return;

        btn.classList.remove('listening', 'waiting', 'wake-word');

        if (state === 'listening') {
            btn.classList.add('listening');
            btn.innerHTML = '<i class="fas fa-microphone"></i>';
            this.updateSpeechDisplay('جاري الاستماع...', true);
        } else if (state === 'waiting') {
            btn.classList.add('waiting');
            btn.innerHTML = '<i class="fas fa-microphone-slash"></i>';
            btn.title = `قل "نعم" ثم الأمر المطلوب`;
            this.updateSpeechDisplay('قل "نعم" ثم الأمر المطلوب');
        } else if (state === 'wake-word') {
            btn.classList.add('wake-word');
            btn.innerHTML = '<i class="fas fa-check"></i>';
        } else {
            btn.innerHTML = '<i class="fas fa-microphone"></i>';
            btn.title = 'اضغط للتحدث أو ESC لإيقاف';
            this.updateSpeechDisplay('قل "نعم" ثم الأمر المطلوب');
        }
    }

    updateSpeechDisplay(text, isListening = false) {
        const display = document.getElementById('voiceSpeechDisplay');
        if (!display) return;
        
        const speechText = display.querySelector('.speech-text');
        if (speechText) {
            speechText.textContent = text;
            display.classList.toggle('listening', isListening);
        }
    }

    showToast(message, type = 'info') {
        if (typeof showToast === 'function') {
            showToast(message, type);
        } else {
            alert(message);
        }
    }
}

// Initialize voice assistant when DOM is ready
let voiceAssistant = null;

document.addEventListener('DOMContentLoaded', () => {
    // Create voice assistant container
    const assistantContainer = document.createElement('div');
    assistantContainer.id = 'voiceAssistantContainer';
    assistantContainer.className = 'voice-assistant-container';
    document.body.appendChild(assistantContainer);

    // Create speech display area
    const speechDisplay = document.createElement('div');
    speechDisplay.id = 'voiceSpeechDisplay';
    speechDisplay.className = 'voice-speech-display';
    speechDisplay.innerHTML = '<span class="speech-label">🎤</span><span class="speech-text">قل "نعم" ثم الأمر المطلوب</span>';
    assistantContainer.appendChild(speechDisplay);

    // Create voice assistant button with visualizer
    const voiceBtn = document.createElement('button');
    voiceBtn.id = 'voiceAssistantBtn';
    voiceBtn.className = 'voice-assistant-btn';
    voiceBtn.innerHTML = '<i class="fas fa-microphone"></i>';
    voiceBtn.title = 'اضغط للتحدث أو ESC لإيقاف';
    assistantContainer.appendChild(voiceBtn);

    // Create visualizer
    const visualizer = document.createElement('div');
    visualizer.id = 'voiceVisualizer';
    visualizer.className = 'voice-visualizer';
    for (let i = 0; i < 7; i++) {
        const bar = document.createElement('div');
        bar.className = 'viz-bar';
        visualizer.appendChild(bar);
    }
    voiceBtn.appendChild(visualizer);

    // Initialize assistant
    voiceAssistant = new VoiceAssistant();

    // Auto-start continuous listening on page load
    setTimeout(() => {
        if (voiceAssistant && !voiceAssistant.isAlwaysListening) {
            voiceAssistant.startContinuousListening();
            console.log('Auto-started continuous listening. Say "نعم" then your command.');
        }
    }, 1000);

    // Click handler
    voiceBtn.addEventListener('click', () => {
        if (voiceAssistant.isAlwaysListening) {
            voiceAssistant.stopContinuousListening();
            if (typeof showToast === 'function') {
                showToast('تم إيقاف الاستماع المستمر', 'info');
            }
        } else {
            voiceAssistant.startContinuousListening();
            if (typeof showToast === 'function') {
                showToast('تم تفعيل الاستماع المستمر. قل "نعم" ثم الأمر المطلوب', 'success');
            }
        }
    });

    // Keyboard shortcut
    let spacePressed = false;
    document.addEventListener('keydown', (e) => {
        if (e.key === ' ' && !spacePressed && !['INPUT', 'TEXTAREA'].includes(e.target.tagName)) {
            spacePressed = true;
            setTimeout(() => { spacePressed = false; }, 500);
        }
        if (e.key === 'v' && spacePressed && voiceAssistant && !['INPUT', 'TEXTAREA'].includes(e.target.tagName)) {
            e.preventDefault();
            if (voiceAssistant.isAlwaysListening) {
                voiceAssistant.stopContinuousListening();
            } else {
                voiceAssistant.startListening();
            }
        }
        if (e.key === 'Escape') {
            if (voiceAssistant) {
                if (voiceAssistant.isListening) {
                    voiceAssistant.stopListening();
                }
                if (voiceAssistant.isAlwaysListening) {
                    voiceAssistant.stopContinuousListening();
                }
            }
        }
    });

    // Stop listening when page is hidden
    document.addEventListener('visibilitychange', () => {
        if (document.hidden && voiceAssistant) {
            voiceAssistant.stopContinuousListening();
        }
    });
});

window.VoiceAssistant = VoiceAssistant;
window.voiceAssistant = voiceAssistant;
