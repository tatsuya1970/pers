document.addEventListener('DOMContentLoaded', () => {
    // --- 多言語辞書 ──
    const I18N_DICT = {
        ja: {
            terms_welcome: "Pers Imageへようこそ",
            terms_intro: `ご利用前に<a href="/static/terms.html" id="terms-link" target="_blank" style="color:var(--accent-blue);">利用規約</a>をご確認ください。<br>「同意して始める」をクリックすることで、利用規約に同意したものとみなします。`,
            terms_link: "利用規約",
            terms_agree_btn: "同意して始める",
            pricing_title: "料金プラン",
            plan_free_name: "Free",
            pricing_monthly: "/月",
            plan_free_desc: "まずは試したい方へ",
            plan_free_feat: "月間 10 回",
            current_plan: "現在のプラン",
            plan_lite_name: "Lite",
            plan_lite_desc: "気軽に使いたい方へ",
            plan_lite_feat: "月間 30 回",
            to_lite_plan: "Liteプランへ",
            plan_recommended: "おすすめ",
            plan_plus_name: "Plus",
            plan_plus_desc: "日々の提案をより高品質に",
            plan_plus_feat: "月間 70 回",
            to_plus_plan: "Plusプランへ",
            plan_max_name: "Max",
            plan_max_desc: "ヘビーユーザー向け",
            plan_max_feat: "月間 200 回",
            to_max_plan: "Maxプランへ",
            processing: "処理中...",
            tickets_remaining_prefix: "チケット残り：",
            tickets_remaining_suffix: " 枚",
            show_pricing: "プラン管理",
            logout: "ログアウト",
            login: "ログイン",
            sidebar_bg_settings: "背景設定",
            sidebar_load_bg: "背景写真を読み込む",
            sidebar_add_elements: "要素の追加",
            sidebar_photo: "写真",
            sidebar_sketch: "イラスト",
            sidebar_blend_btn: "背景に合成（チケット1枚）",
            sidebar_text_instruction: "テキスト指示",
            sidebar_placeholder_instruction: "例：空を夕方にする、木を増やす...",
            sidebar_ai_instruct_btn: "テキスト指示を実行（チケット1枚）",
            sidebar_export_btn: "画像を保存 (PNG)",
            footer_feedback: "ご意見・ご質問・バグ報告",
            footer_terms: "利用規約",
            footer_tokusho: "特定商取引法に基づく表記",
            guide_title: "Pers Image - AIで建物パースを簡単合成",
            guide_desc: "土地・建物の写真や画像をもとに、AIが簡易パースをその場でスピーディに生成します。<br>正式なパース作成前の社内協議や、関係者との認識合わせにお役立てください。<br>まず右上の「ログイン」からGoogleアカウントでサインインしてください。",
            guide_steps: "<span>① 背景写真を読み込む</span><span>→</span><span>② 建物画像を追加</span><span>→</span><span>③ 合成ボタンを押す</span>",
            tooltip_undo: "元に戻す",
            tooltip_clear: "クリア",

            // JS messages
            msg_load_bg_first: "先に背景をアップロードしてください。",
            msg_insufficient_tickets: "チケットが不足しています。プランのアップグレードをご検討ください。",
            msg_server_error_502: "サーバーエラーが発生しました（502）。\n\nチケットが消費されている可能性があります。\nページを再読み込みしてチケット数をご確認ください。\n消費されていた場合はお問い合わせください。",
            msg_clear_confirm: "キャンバスをクリアしますか？\n現在の作業内容はすべて消去されます。",
            msg_logout_confirm: "ログアウトしますか？\n現在画面に表示されている画像は、ログアウトすると消去されます。\nよろしいですか？",
            msg_login_required: "ログインが必要です。",
            msg_network_error: "通信エラー",
            msg_request_timeout: "処理がタイムアウトしました（3分）。\n\nサーバー側の処理がまだ完了していない場合、チケットは消費されません。\nページを再読み込みしてチケット数をご確認ください。",
            msg_plan_changed: "{plan}プランに変更しました。\n\n※ 差額は次回の請求日にまとめて精算されます。",
            msg_plan_change_failed: "変更に失敗しました。",
            msg_change_to_free_confirm: "無料プランに変更しますか？\n\n⚠️ チケットが減る可能性があります。無料プランの上限（10枚）を超えている場合、10枚にリセットされます。\n\n※ 現在の契約期間が終了するまで、Stripeによる課金は継続されます。\n期間終了後に自動更新が停止し、無料プランに切り替わります。",
            msg_change_to_free_accepted: "無料プランへの変更を受け付けました。\n\n現在の契約期間が終了するまでは引き続きご利用いただけます。\n期間終了後に自動更新が停止します。\n\n※ Stripeからの請求は現在の期間終了後に停止します。",
            
            // Timer texts
            timer_blending: "画像を馴染ませています... 通常20〜60秒かかります",
            timer_instruction: "AIによる指示を実行中... 通常20〜60秒かかります",

            // Toast texts
            toast_blend_complete: "✓ 合成完了（残り {credits} 回）",
            toast_instruct_complete: "✓ 完了（残り {credits} 回）",
            
            // General text
            change_to_free_plan_btn: "無料プランに変更"
        },
        en: {
            terms_welcome: "Welcome to Pers Image",
            terms_intro: `Please review the <a href="/static/terms_en.html" id="terms-link" target="_blank" style="color:var(--accent-blue);">Terms of Service</a> before using the service.<br>By clicking "Agree and Start", you are deemed to have agreed to the terms.`,
            terms_link: "Terms of Service",
            terms_agree_btn: "Agree and Start",
            pricing_title: "Pricing Plans",
            plan_free_name: "Free",
            pricing_monthly: "/mo",
            plan_free_desc: "For those who want to try first",
            plan_free_feat: "10 tickets (one-time)",
            current_plan: "Current Plan",
            plan_lite_name: "Lite",
            plan_lite_desc: "For casual users",
            plan_lite_feat: "30 tickets / month",
            to_lite_plan: "Upgrade to Lite",
            plan_recommended: "Recommended",
            plan_plus_name: "Plus",
            plan_plus_desc: "For higher quality daily proposals",
            plan_plus_feat: "70 tickets / month",
            to_plus_plan: "Upgrade to Plus",
            plan_max_name: "Max",
            plan_max_desc: "For heavy users",
            plan_max_feat: "200 tickets / month",
            to_max_plan: "Upgrade to Max",
            processing: "Processing...",
            tickets_remaining_prefix: "Tickets left: ",
            tickets_remaining_suffix: "",
            show_pricing: "Manage Plan",
            logout: "Logout",
            login: "Login",
            sidebar_bg_settings: "Background Setting",
            sidebar_load_bg: "Load Background Photo",
            sidebar_add_elements: "Add Elements",
            sidebar_photo: "Photo",
            sidebar_sketch: "Sketch",
            sidebar_blend_btn: "Blend into Background (1 ticket)",
            sidebar_text_instruction: "Text Instructions",
            sidebar_placeholder_instruction: "e.g., Make the sky evening, add more trees...",
            sidebar_ai_instruct_btn: "Run Text Instruction (1 ticket)",
            sidebar_export_btn: "Save Image (PNG)",
            footer_feedback: "Feedback & Support",
            footer_terms: "Terms of Service",
            footer_tokusho: "Act on Specified Commercial Transactions",
            guide_title: "Pers Image - Easy AI Building Perspective Synthesis",
            guide_desc: "Based on photos of land and buildings, AI generates simple perspectives on the spot.<br>Useful for internal discussions and aligning with stakeholders before creating formal perspective drawings.<br>Please sign in with your Google account from the \"Login\" button at the top right.",
            guide_steps: "<span>① Load Background Photo</span><span>→</span><span>② Add Building Image</span><span>→</span><span>③ Press Blend Button</span>",
            tooltip_undo: "Undo",
            tooltip_clear: "Clear",

            // JS messages
            msg_load_bg_first: "Please upload a background photo first.",
            msg_insufficient_tickets: "Insufficient tickets. Please consider upgrading your plan.",
            msg_server_error_502: "A server error occurred (502).\n\nTickets might have been consumed.\nPlease reload the page to check your ticket balance.\nIf they were consumed, please contact support.",
            msg_clear_confirm: "Are you sure you want to clear the canvas?\nAll current work will be lost.",
            msg_logout_confirm: "Are you sure you want to log out?\nThe image currently displayed on the screen will be cleared upon logout. Continue?",
            msg_login_required: "Login required.",
            msg_network_error: "Communication error",
            msg_request_timeout: "The request timed out (3 minutes).\n\nIf processing had not finished on the server, no ticket was consumed.\nPlease reload the page to check your ticket balance.",
            msg_plan_changed: "Changed to {plan} plan.\n\n* The price difference will be adjusted on your next billing cycle.",
            msg_plan_change_failed: "Failed to change plan.",
            msg_change_to_free_confirm: "Are you sure you want to change to the Free plan?\n\n⚠️ Your tickets may be reduced. If your tickets exceed the Free plan limit (10), they will be reset to 10.\n\n* Your Stripe subscription billing will continue until the end of the current billing cycle. It will automatically stop renewing and downgrade to Free at that point.",
            msg_change_to_free_accepted: "We have received your request to downgrade to the Free plan.\n\nYou can continue to use the service until the end of the current billing period.\nStripe billing will stop after the current period.",
            
            // Timer texts
            timer_blending: "Blending image... Usually takes 20-60 seconds",
            timer_instruction: "Running AI instruction... Usually takes 20-60 seconds",

            // Toast texts
            toast_blend_complete: "✓ Blending complete ({credits} left)",
            toast_instruct_complete: "✓ Completed ({credits} left)",
            
            // General text
            change_to_free_plan_btn: "Downgrade to Free"
        }
    };

    // --- メタタグ（SEO/OGP）用の多言語辞書 ──
    const META_I18N = {
        ja: {
            title: "Pers Image - AIで建物パースを簡単合成",
            description: "土地・建物の写真からAIが簡易パースをスピーディに生成。社内協議や関係者との認識合わせに最適な建物パース合成ツールです。",
            keywords: "建物パース,AI合成,建築パース,不動産,簡易パース,写真合成,Pers Image",
            ogTitle: "Pers Image - AIで建物パースを簡単合成",
            ogDescription: "土地・建物の写真からAIが簡易パースをスピーディに生成。社内協議や関係者との認識合わせに最適。",
            ogLocale: "ja_JP",
            schemaDescription: "土地・建物の写真からAIが簡易パースをスピーディに生成する建物パース合成ツール"
        },
        en: {
            title: "Pers Image - Easy AI Building Perspective Synthesis",
            description: "AI quickly generates simple building perspectives from photos of land and buildings. The ideal perspective synthesis tool for internal discussions and aligning with stakeholders.",
            keywords: "building perspective,AI synthesis,architectural rendering,real estate,quick perspective,photo composition,Pers Image",
            ogTitle: "Pers Image - Easy AI Building Perspective Synthesis",
            ogDescription: "AI quickly generates simple building perspectives from photos of land and buildings. Ideal for internal discussions and aligning with stakeholders.",
            ogLocale: "en_US",
            schemaDescription: "A building perspective synthesis tool that uses AI to quickly generate simple perspectives from photos of land and buildings."
        }
    };

    const setMetaContent = (selector, content) => {
        const el = document.querySelector(selector);
        if (el) el.setAttribute('content', content);
    };

    function applyMetaLanguage(lang) {
        const meta = META_I18N[lang] || META_I18N.ja;

        document.title = meta.title;
        setMetaContent('meta[name="description"]', meta.description);
        setMetaContent('meta[name="keywords"]', meta.keywords);

        setMetaContent('meta[property="og:title"]', meta.ogTitle);
        setMetaContent('meta[property="og:description"]', meta.ogDescription);
        setMetaContent('meta[property="og:locale"]', meta.ogLocale);
        setMetaContent('meta[property="og:locale:alternate"]', lang === 'en' ? 'ja_JP' : 'en_US');

        setMetaContent('meta[name="twitter:title"]', meta.ogTitle);
        setMetaContent('meta[name="twitter:description"]', meta.ogDescription);

        const ldScript = document.getElementById('ld-json');
        if (ldScript) {
            try {
                const data = JSON.parse(ldScript.textContent);
                data.description = meta.schemaDescription;
                ldScript.textContent = JSON.stringify(data);
            } catch (e) {
                // JSON-LDのパースに失敗しても表示には影響しないため無視
            }
        }
    }

    const getSystemLanguage = () => {
        const params = new URLSearchParams(window.location.search);
        const urlLang = params.get('lang');
        if (urlLang === 'en' || urlLang === 'ja') return urlLang;

        const localLang = localStorage.getItem('pers_lang');
        if (localLang === 'en' || localLang === 'ja') return localLang;

        const navLang = navigator.language || navigator.userLanguage;
        if (navLang && navLang.toLowerCase().startsWith('en')) return 'en';
        return 'ja';
    };

    let currentLang = getSystemLanguage();
    document.documentElement.lang = currentLang;

    const AI_REQUEST_TIMEOUT_MS = 180000;
    const UPLOAD_MAX_EDGE = 2048;

    function getApiErrorMessage(err) {
        if (err?.name === 'AbortError') {
            return I18N_DICT[currentLang].msg_request_timeout;
        }
        if (!err?.message || err.message === 'Failed to fetch') {
            return I18N_DICT[currentLang].msg_network_error;
        }
        return err.message;
    }

    function applyLanguage(lang) {
        currentLang = lang;
        document.documentElement.lang = lang;
        localStorage.setItem('pers_lang', lang);

        const btnJa = document.getElementById('lang-ja');
        const btnEn = document.getElementById('lang-en');
        if (btnJa && btnEn) {
            if (lang === 'ja') {
                btnJa.style.fontWeight = 'bold';
                btnJa.style.color = 'var(--accent-blue)';
                btnEn.style.fontWeight = 'normal';
                btnEn.style.color = 'var(--text-secondary)';
            } else {
                btnEn.style.fontWeight = 'bold';
                btnEn.style.color = 'var(--accent-blue)';
                btnJa.style.fontWeight = 'normal';
                btnJa.style.color = 'var(--text-secondary)';
            }
        }

        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            const translation = I18N_DICT[lang][key];
            if (translation) {
                if (key === 'terms_intro' || key === 'guide_steps' || key === 'guide_desc') {
                    el.innerHTML = translation;
                } else {
                    el.textContent = translation;
                }
            }
        });

        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.getAttribute('data-i18n-placeholder');
            const translation = I18N_DICT[lang][key];
            if (translation) el.placeholder = translation;
        });

        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            const translation = I18N_DICT[lang][key];
            if (translation) el.title = translation;
        });

        const termsLink = document.getElementById('terms-link');
        const termsFooterLink = document.getElementById('terms-footer-link');
        const termsPath = lang === 'en' ? '/static/terms_en.html' : '/static/terms.html';
        if (termsLink) termsLink.setAttribute('href', termsPath);
        if (termsFooterLink) termsFooterLink.setAttribute('href', termsPath);

        // タイトル・メタ情報（description / keywords / OGP / Twitter / JSON-LD）を言語に合わせて更新
        applyMetaLanguage(lang);

        // 動的な「無料プランに変更」ボタンのテキストや「現在のプラン」テキストなども更新する必要があるが、それはログイン状態変化時(sync時)に別途処理される。
    }

    const langBtnJa = document.getElementById('lang-ja');
    const langBtnEn = document.getElementById('lang-en');
    if (langBtnJa) langBtnJa.addEventListener('click', () => applyLanguage('ja'));
    if (langBtnEn) langBtnEn.addEventListener('click', () => applyLanguage('en'));

    // 初期適用
    applyLanguage(currentLang);

    // --- UI要素 ---
    const wrapper = document.getElementById('canvas-wrapper');
    const loadingOverlay = document.getElementById('loading-overlay');
    const clickBlocker = document.getElementById('click-blocker');

    // --- ロギング ---
    function addLog(msg, type = 'info') {
        const time = new Date().toLocaleTimeString('ja-JP', { hour12: false });
        const logMsg = `[${time}] [${type.toUpperCase()}] ${msg}`;
        if (type === 'error') console.error(logMsg);
        else if (type === 'warn') console.warn(logMsg);
        else console.log(logMsg);
    }

    function setControlsDisabled(disabled) {
        document.querySelectorAll('button, input, textarea').forEach(el => {
            el.disabled = disabled;
        });
        if (clickBlocker) {
            if (disabled) clickBlocker.classList.add('active');
            else clickBlocker.classList.remove('active');
        }
        if (!disabled) {
            if (typeof updateFeatureButtonsState === 'function') updateFeatureButtonsState();
            const undoBtn = document.getElementById('undo-btn');
            if (undoBtn && typeof canvasHistory !== 'undefined') {
                undoBtn.disabled = (canvasHistory.length <= 1);
            }
        }
    }

    const dataUrlToBlob = async (url) => (await fetch(url)).blob();

    function resizeCanvasForUpload(sourceCanvas, maxEdge = UPLOAD_MAX_EDGE) {
        const w = sourceCanvas.width;
        const h = sourceCanvas.height;
        const maxDim = Math.max(w, h);
        if (!maxDim || maxDim <= maxEdge) {
            return { canvas: sourceCanvas, scale: 1 };
        }
        const scale = maxEdge / maxDim;
        const out = document.createElement('canvas');
        out.width = Math.max(1, Math.round(w * scale));
        out.height = Math.max(1, Math.round(h * scale));
        out.getContext('2d').drawImage(sourceCanvas, 0, 0, out.width, out.height);
        return { canvas: out, scale };
    }

    async function resizeBlobForUpload(blob, maxEdge = UPLOAD_MAX_EDGE, mime = 'image/jpeg', quality = 0.85) {
        const bitmap = await createImageBitmap(blob);
        const maxDim = Math.max(bitmap.width, bitmap.height);
        if (!maxDim || maxDim <= maxEdge) {
            bitmap.close();
            return blob;
        }
        const scale = maxEdge / maxDim;
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(bitmap.width * scale));
        canvas.height = Math.max(1, Math.round(bitmap.height * scale));
        canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        bitmap.close();
        return new Promise((resolve) => canvas.toBlob(resolve, mime, quality));
    }

    // --- トースト通知 ---
    function showToast(message, duration = 2800) {
        let toast = document.getElementById('pers-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'pers-toast';
            toast.style.cssText = [
                'position:fixed', 'bottom:28px', 'left:50%', 'transform:translateX(-50%)',
                'background:#111827', 'color:#fff', 'padding:10px 22px', 'border-radius:8px',
                'font-size:13px', 'font-family:inherit', 'z-index:9999',
                'opacity:0', 'transition:opacity 0.25s', 'pointer-events:none',
                'white-space:nowrap', 'box-shadow:0 4px 12px rgba(0,0,0,0.25)'
            ].join(';');
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.style.opacity = '1';
        clearTimeout(toast._timer);
        toast._timer = setTimeout(() => { toast.style.opacity = '0'; }, duration);
    }

    // --- ローディングタイマー ---
    let _loadingTimerID = null;
    function startLoadingTimer(baseText) {
        const p = loadingOverlay ? loadingOverlay.querySelector('p') : null;
        if (!p) return;
        let secs = 0;
        const suffix = currentLang === 'en' ? 's' : '秒';
        p.textContent = baseText + ` (0${suffix})`;
        _loadingTimerID = setInterval(() => {
            secs++;
            p.textContent = baseText + ` (${secs}${suffix})`;
        }, 1000);
    }
    function stopLoadingTimer() {
        if (_loadingTimerID) { clearInterval(_loadingTimerID); _loadingTimerID = null; }
    }

    // --- クレジット表示更新 ---
    async function refreshCredits(token) {
        if (!token) return;
        try {
            const d = await fetch('/api/user/sync', {
                method: 'POST', headers: { 'Authorization': `Bearer ${token}`, 'Accept-Language': currentLang }
            }).then(r => r.json());
            const remaining = d.credits ?? 0;
            document.getElementById('credit-count').textContent = remaining;
            return remaining;
        } catch (err) {
            console.warn('refreshCredits failed:', err);
        }
    }

    // --- Fabric.js キャンバス初期化 ---
    if (!document.getElementById('main-canvas')) return;
    const fCanvas = new fabric.Canvas('main-canvas', {
        preserveObjectStacking: true,
        selection: false
    });

    if (wrapper) {
        fCanvas.setWidth(wrapper.clientWidth * 0.9);
        fCanvas.setHeight(wrapper.clientHeight * 0.9);
    }

    function updateFeatureButtonsState() {
        const hasBg = !!fCanvas.backgroundImage;
        const addPhotoBtn = document.getElementById('add-photo-btn');
        const addSketchBtn = document.getElementById('add-sketch-btn');
        const instructBtn = document.getElementById('ai-instruct-btn');
        const instructInput = document.querySelector('.textarea');
        const exportBtn = document.getElementById('export-btn');
        const blendBtn = document.getElementById('blend-btn');
        const clearBtn = document.getElementById('clear-btn');

        if (addPhotoBtn) addPhotoBtn.disabled = !hasBg;
        if (addSketchBtn) addSketchBtn.disabled = !hasBg;
        if (instructBtn) instructBtn.disabled = !hasBg;
        if (instructInput) instructInput.disabled = !hasBg;
        if (exportBtn) exportBtn.disabled = !hasBg;
        if (clearBtn) clearBtn.disabled = !hasBg;
        // 合成ボタン: 選択オブジェクトがないと無効（選択イベントで管理）
        if (blendBtn) blendBtn.disabled = true;
    }
    updateFeatureButtonsState();

    let originalBgBlob = null;

    // 背景セットヘルパー
    function setBackgroundFromURL(url, updateCanvasSize = false) {
        fabric.Image.fromURL(url, (img) => {
            if (updateCanvasSize && wrapper) {
                const scale = Math.min(
                    (wrapper.clientWidth * 0.9) / img.width,
                    (wrapper.clientHeight * 0.9) / img.height
                );
                if (scale < 1) {
                    fCanvas.setZoom(scale);
                    fCanvas.setWidth(img.width * scale);
                    fCanvas.setHeight(img.height * scale);
                } else {
                    fCanvas.setZoom(1);
                    fCanvas.setWidth(img.width);
                    fCanvas.setHeight(img.height);
                }
            }
            fCanvas.setBackgroundImage(img, fCanvas.renderAll.bind(fCanvas), {
                originX: 'left',
                originY: 'top',
                crossOrigin: 'anonymous'
            });
            saveHistory();
            updateFeatureButtonsState();
        });
    }

    // --- 背景アップロード ---
    const bgInput = document.getElementById('bg-input');
    const openBgBtn = document.getElementById('open-bg-btn');
    if (openBgBtn && bgInput) {
        openBgBtn.addEventListener('click', () => bgInput.click());
        bgInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                originalBgBlob = e.target.files[0];
                const reader = new FileReader();
                reader.onload = (ev) => setBackgroundFromURL(ev.target.result, true);
                reader.readAsDataURL(originalBgBlob);
            }
        });
    }

    // --- 建物を追加 ---
    const photoInput = document.createElement('input');
    photoInput.type = 'file';
    photoInput.accept = 'image/*';
    photoInput.style.display = 'none';
    document.body.appendChild(photoInput);

    const addPhotoBtn = document.getElementById('add-photo-btn');
    if (addPhotoBtn) {
        addPhotoBtn.addEventListener('click', () => {
            if (addPhotoBtn.disabled || !fCanvas.backgroundImage) return;
            photoInput.click();
        });
    }

    photoInput.addEventListener('change', async (e) => {
        if (e.target.files.length > 0 && fCanvas.backgroundImage) {
            const file = e.target.files[0];
            const reader = new FileReader();
            reader.onload = (ev) => {
                fabric.Image.fromURL(ev.target.result, (img) => {
                    const lw = fCanvas.getWidth() / fCanvas.getZoom();
                    const lh = fCanvas.getHeight() / fCanvas.getZoom();
                    img.set({
                        left: lw / 2, top: lh / 2,
                        originX: 'center', originY: 'center',
                        cornerColor: '#3b82f6', transparentCorners: false
                    });
                    if (img.width > lw * 0.5) img.scaleToWidth(lw * 0.5);
                    fCanvas.add(img);
                    fCanvas.setActiveObject(img);
                    saveHistory();
                });
            };
            reader.readAsDataURL(file);
        } else if (!fCanvas.backgroundImage) {
            alert(I18N_DICT[currentLang].msg_load_bg_first);
        }
    });

    // --- イラスト変換 ---
    const sketchBtn = document.getElementById('add-sketch-btn');
    const sketchInput = document.createElement('input');
    sketchInput.type = 'file';
    sketchInput.accept = 'image/*';
    sketchInput.style.display = 'none';
    document.body.appendChild(sketchInput);

    if (sketchBtn) {
        sketchBtn.addEventListener('click', () => {
            if (sketchBtn.disabled || !fCanvas.backgroundImage) return;
            sketchInput.click();
        });
    }

    sketchInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0 && fCanvas.backgroundImage) {
            const reader = new FileReader();
            reader.onload = (ev) => {
                fabric.Image.fromURL(ev.target.result, (img) => {
                    const lw = fCanvas.getWidth() / fCanvas.getZoom();
                    const lh = fCanvas.getHeight() / fCanvas.getZoom();
                    img.set({
                        left: lw / 2, top: lh / 2,
                        originX: 'center', originY: 'center',
                        cornerColor: '#f59e0b', transparentCorners: false,
                        opacity: 0.9
                    });
                    img.isSketchLayer = true;
                    if (img.width > lw * 0.5) img.scaleToWidth(lw * 0.5);
                    fCanvas.add(img);
                    fCanvas.setActiveObject(img);
                    saveHistory();
                });
            };
            reader.readAsDataURL(e.target.files[0]);
        }
    });

    // --- AI編集指示 ---
    const instructBtn = document.getElementById('ai-instruct-btn');
    const instructInput = document.querySelector('.textarea');
    if (instructBtn && instructInput) {
        instructBtn.addEventListener('click', async () => {
            if (instructBtn.disabled || !fCanvas.backgroundImage) return;
            const text = instructInput.value.trim();
            if (!text || !fCanvas.backgroundImage) return;

            setControlsDisabled(true);
            if (loadingOverlay) {
                loadingOverlay.classList.remove('hidden');
                startLoadingTimer(I18N_DICT[currentLang].timer_instruction);
            }

            try {
                const multiplier = 1 / fCanvas.getZoom();
                const dataUrl = fCanvas.toDataURL({ format: 'png', multiplier: multiplier });
                let blob = await dataUrlToBlob(dataUrl);
                blob = await resizeBlobForUpload(blob);

                const quality = document.getElementById('quality-select')?.value || 'high';
                const formData = new FormData();
                formData.append('file', blob, 'canvas.png');
                formData.append('instruction', text);
                formData.append('quality', quality);

                const token = window.getIdToken ? await window.getIdToken() : null;
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort('timeout'), AI_REQUEST_TIMEOUT_MS);
                let res;
                try {
                    res = await fetch('/api/instruction', {
                        method: 'POST',
                        body: formData,
                        headers: token ? { 'Authorization': `Bearer ${token}`, 'Accept-Language': currentLang } : { 'Accept-Language': currentLang },
                        signal: controller.signal
                    });
                } finally {
                    clearTimeout(timer);
                }
                if (res.status === 402) {
                    alert(I18N_DICT[currentLang].msg_insufficient_tickets);
                    const modal = document.getElementById('pricing-modal');
                    if (modal) modal.classList.remove('hidden');
                    return;
                }
                const data = await res.json();
                if (data.error) throw new Error(data.error);

                setBackgroundFromURL(data.image_base64, false);
                fCanvas.clear();
                instructInput.value = '';
                const remaining = await refreshCredits(token);
                showToast(I18N_DICT[currentLang].toast_instruct_complete.replace('{credits}', remaining ?? '?'));
            } catch (err) {
                alert(getApiErrorMessage(err));
            } finally {
                stopLoadingTimer();
                setControlsDisabled(false);
                if (loadingOverlay) loadingOverlay.classList.add('hidden');
            }
        });
    }

    // --- Undo ---
    let canvasHistory = [];
    let isUndoing = false;
    const undoBtn = document.getElementById('undo-btn');

    function saveHistory() {
        if (isUndoing) return;
        canvasHistory.push(JSON.stringify(fCanvas.toJSON(['isSketchLayer'])));
        if (canvasHistory.length > 20) canvasHistory.shift();
        if (undoBtn) undoBtn.disabled = (canvasHistory.length <= 1);
    }

    if (undoBtn) {
        undoBtn.addEventListener('click', () => {
            if (canvasHistory.length <= 1) return;
            isUndoing = true;
            canvasHistory.pop();
            const prevState = canvasHistory[canvasHistory.length - 1];
            fCanvas.loadFromJSON(prevState, () => {
                fCanvas.renderAll();
                isUndoing = false;
                undoBtn.disabled = (canvasHistory.length <= 1);
                updateFeatureButtonsState();
                // ファイル入力をリセット（同じファイルを再選択できるようにする）
                if (bgInput) bgInput.value = '';
                photoInput.value = '';
                sketchInput.value = '';
            });
        });
    }
    fCanvas.on('object:modified', saveHistory);

    // --- 選択状態に応じて「馴染ませる」ボタンを制御 ---
    function updateBlendBtnState() {
        const blendBtn = document.getElementById('blend-btn');
        if (!blendBtn) return;
        const hasObj = !!fCanvas.getActiveObject();
        const hasBg = !!fCanvas.backgroundImage;
        blendBtn.disabled = !(hasObj && hasBg);
    }
    fCanvas.on('selection:created', updateBlendBtnState);
    fCanvas.on('selection:updated', updateBlendBtnState);
    fCanvas.on('selection:cleared', updateBlendBtnState);

    // --- 画像を馴染ませる ---
    const blendBtn = document.getElementById('blend-btn');
    if (blendBtn) {
        blendBtn.addEventListener('click', async () => {
            const obj = fCanvas.getActiveObject();
            if (!obj || !fCanvas.backgroundImage) return;

            setControlsDisabled(true);
            if (loadingOverlay) {
                loadingOverlay.classList.remove('hidden');
                startLoadingTimer(I18N_DICT[currentLang].timer_blending);
            }

            try {
                // 背景画像をblobとして取得
                const bgEl = fCanvas.backgroundImage.getElement();
                const bgTmp = document.createElement('canvas');
                bgTmp.width = bgEl.naturalWidth || bgEl.width;
                bgTmp.height = bgEl.naturalHeight || bgEl.height;
                bgTmp.getContext('2d').drawImage(bgEl, 0, 0);
                const bgScaled = resizeCanvasForUpload(bgTmp);
                const bgBlob = await new Promise(resolve => bgScaled.canvas.toBlob(resolve, 'image/jpeg', 0.85));

                // 建物画像をblobとして取得（オリジナルサイズ）
                const bldEl = obj.getElement();
                const bldTmp = document.createElement('canvas');
                bldTmp.width = bldEl.naturalWidth || bldEl.width;
                bldTmp.height = bldEl.naturalHeight || bldEl.height;
                bldTmp.getContext('2d').drawImage(bldEl, 0, 0);
                const bldScaled = resizeCanvasForUpload(bldTmp);
                const bldBlob = await new Promise(resolve => bldScaled.canvas.toBlob(resolve, 'image/png'));

                // 配置情報（背景画像座標。縮小した場合は同じ倍率で合わせる）
                const coordScale = bgScaled.scale;
                const cx = obj.left * coordScale;
                const cy = obj.top * coordScale;
                const w = obj.getScaledWidth() * coordScale;
                const h = obj.getScaledHeight() * coordScale;
                const angle = obj.angle || 0;
                const isSketch = !!obj.isSketchLayer;

                const quality = document.getElementById('quality-select')?.value || 'high';
                const formData = new FormData();
                formData.append('bg_file', bgBlob, 'background.png');
                formData.append('bld_file', bldBlob, 'building.png');
                formData.append('cx', cx);
                formData.append('cy', cy);
                formData.append('width', w);
                formData.append('height', h);
                formData.append('angle', angle);
                formData.append('is_sketch', isSketch);
                formData.append('quality', quality);

                const token = window.getIdToken ? await window.getIdToken() : null;
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort('timeout'), AI_REQUEST_TIMEOUT_MS);
                let res;
                try {
                    res = await fetch('/api/blend', {
                        method: 'POST',
                        body: formData,
                        headers: token ? { 'Authorization': `Bearer ${token}`, 'Accept-Language': currentLang } : { 'Accept-Language': currentLang },
                        signal: controller.signal
                    });
                } finally {
                    clearTimeout(timer);
                }
                if (res.status === 402) {
                    alert(I18N_DICT[currentLang].msg_insufficient_tickets);
                    const modal = document.getElementById('pricing-modal');
                    if (modal) modal.classList.remove('hidden');
                    return;
                }
                if (res.status === 502 || res.status === 503) {
                    alert(I18N_DICT[currentLang].msg_server_error_502);
                    return;
                }
                const data = await res.json();
                if (data.error) throw new Error(data.error);

                // 建物オブジェクトを削除して結果を背景に反映
                fCanvas.remove(obj);
                setBackgroundFromURL(data.image_base64, false);
                const remaining = await refreshCredits(token);
                showToast(I18N_DICT[currentLang].toast_blend_complete.replace('{credits}', remaining ?? '?'));
            } catch (err) {
                alert(getApiErrorMessage(err));
            } finally {
                stopLoadingTimer();
                setControlsDisabled(false);
                if (loadingOverlay) loadingOverlay.classList.add('hidden');
            }
        });
    }

    // --- クリア ---
    function clearCanvas() {
        fCanvas.clear();
        fCanvas.setBackgroundImage(null, fCanvas.renderAll.bind(fCanvas));
        originalBgBlob = null;
        canvasHistory = [];
        if (bgInput) bgInput.value = '';
        updateFeatureButtonsState();
        const undoBtn = document.getElementById('undo-btn');
        if (undoBtn) undoBtn.disabled = true;
    }
    window.clearCanvas = clearCanvas;

    const clearBtn = document.getElementById('clear-btn');
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            if (!fCanvas.backgroundImage) return;
            if (!confirm(I18N_DICT[currentLang].msg_clear_confirm)) return;
            clearCanvas();
        });
    }

    // --- PNG保存 ---
    const exportBtn = document.getElementById('export-btn');
    if (exportBtn) {
        exportBtn.addEventListener('click', () => {
            if (!fCanvas.backgroundImage) return;
            fCanvas.discardActiveObject();
            fCanvas.renderAll();
            const link = document.createElement('a');
            link.download = 'pers_export.png';
            link.href = fCanvas.toDataURL({ format: 'png', multiplier: 1 / fCanvas.getZoom() });
            link.click();
        });
    }

// --- 決済ロジック ---
    async function handleCheckout(params) {
        if (!window.currentUserUID) { alert(I18N_DICT[currentLang].msg_login_required); return; }
        const token = window.getIdToken ? await window.getIdToken() : null;
        if (!token) { alert(I18N_DICT[currentLang].msg_login_required); return; }
        try {
            if (loadingOverlay) loadingOverlay.classList.remove('hidden');

            // 既存の有料サブスクがある場合 → 日割り精算でプラン変更
            const currentPlan = (window.currentUserPlan || 'free').toLowerCase();
            if (params.plan && currentPlan !== 'free') {
                const res = await fetch('/api/change-plan', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}`, 'Accept-Language': currentLang },
                    body: JSON.stringify({ plan: params.plan })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    const label = params.plan.charAt(0).toUpperCase() + params.plan.slice(1);
                    alert(I18N_DICT[currentLang].msg_plan_changed.replace('{plan}', label));
                    location.reload();
                } else {
                    alert(data.error || I18N_DICT[currentLang].msg_plan_change_failed);
                }
                return;
            }

            // 新規サブスク（FreeからのアップグレードはStripe Checkout）
            const res = await fetch('/api/create-checkout-session', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}`, 'Accept-Language': currentLang },
                body: JSON.stringify(params)
            });
            const data = await res.json();
            if (data.url) window.location.href = data.url;
            else alert(data.error || I18N_DICT[currentLang].msg_plan_change_failed);
        } catch (e) { alert(I18N_DICT[currentLang].msg_network_error); }
        finally { if (loadingOverlay) loadingOverlay.classList.add('hidden'); }
    }

    document.addEventListener('click', (e) => {
        const pBtn = e.target.closest('.btn-plan[data-plan]');
        if (pBtn) return handleCheckout({ plan: pBtn.getAttribute('data-plan') });
        const aBtn = e.target.closest('.btn-addon[data-addon]');
        if (aBtn) return handleCheckout({ addon: aBtn.getAttribute('data-addon') });
    });
});
