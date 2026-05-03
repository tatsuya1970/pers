document.addEventListener('DOMContentLoaded', () => {
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
            alert('先に背景をアップロードしてください。');
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
                loadingOverlay.querySelector('p').textContent = 'AIによる指示を実行中...';
                loadingOverlay.classList.remove('hidden');
            }

            try {
                const multiplier = 1 / fCanvas.getZoom();
                const dataUrl = fCanvas.toDataURL({ format: 'png', multiplier: multiplier });
                const blob = await dataUrlToBlob(dataUrl);

                const quality = document.getElementById('quality-select')?.value || 'high';
                const formData = new FormData();
                formData.append('file', blob, 'canvas.png');
                formData.append('instruction', text);
                formData.append('quality', quality);

                const uid = window.currentUserUID;
                const res = await fetch('/api/instruction', {
                    method: 'POST',
                    body: formData,
                    headers: uid ? { 'X-User-ID': uid } : {}
                });
                const data = await res.json();
                if (data.error) throw new Error(data.error);

                setBackgroundFromURL(data.image_base64, false);
                fCanvas.clear();
                instructInput.value = '';
            } catch (err) {
                alert(err.message);
            } finally {
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
                loadingOverlay.querySelector('p').textContent = '画像を馴染ませています...';
                loadingOverlay.classList.remove('hidden');
            }

            try {
                // 背景画像をblobとして取得
                const bgEl = fCanvas.backgroundImage.getElement();
                const bgTmp = document.createElement('canvas');
                bgTmp.width = bgEl.naturalWidth || bgEl.width;
                bgTmp.height = bgEl.naturalHeight || bgEl.height;
                bgTmp.getContext('2d').drawImage(bgEl, 0, 0);
                const bgBlob = await new Promise(resolve => bgTmp.toBlob(resolve, 'image/png'));

                // 建物画像をblobとして取得（オリジナルサイズ）
                const bldEl = obj.getElement();
                const bldTmp = document.createElement('canvas');
                bldTmp.width = bldEl.naturalWidth || bldEl.width;
                bldTmp.height = bldEl.naturalHeight || bldEl.height;
                bldTmp.getContext('2d').drawImage(bldEl, 0, 0);
                const bldBlob = await new Promise(resolve => bldTmp.toBlob(resolve, 'image/png'));

                // 配置情報（ロジカル座標 = 背景画像座標）
                const cx = obj.left;
                const cy = obj.top;
                const w = obj.getScaledWidth();
                const h = obj.getScaledHeight();
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

                const uid = window.currentUserUID;
                const res = await fetch('/api/blend', {
                    method: 'POST',
                    body: formData,
                    headers: uid ? { 'X-User-ID': uid } : {}
                });
                const data = await res.json();
                if (data.error) throw new Error(data.error);

                // 建物オブジェクトを削除して結果を背景に反映
                fCanvas.remove(obj);
                setBackgroundFromURL(data.image_base64, false);
                // クレジット残高を再取得して表示更新
                if (uid) {
                    fetch('/api/user/sync', { method: 'POST', headers: { 'X-User-ID': uid } })
                        .then(r => r.json()).then(d => {
                            document.getElementById('credit-count').textContent = d.credits ?? 0;
                        });
                }
            } catch (err) {
                alert(err.message);
            } finally {
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
        const uid = window.currentUserUID;
        if (!uid) { alert('ログインが必要です。'); return; }
        try {
            if (loadingOverlay) loadingOverlay.classList.remove('hidden');

            // 既存の有料サブスクがある場合 → 日割り精算でプラン変更
            const currentPlan = window.currentUserPlan || 'free';
            if (params.plan && currentPlan !== 'free') {
                const res = await fetch('/api/change-plan', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-User-ID': uid },
                    body: JSON.stringify({ plan: params.plan })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    const label = params.plan.charAt(0).toUpperCase() + params.plan.slice(1);
                    alert(`${label}プランに変更しました。`);
                    location.reload();
                } else {
                    alert(data.error || 'エラーが発生しました');
                }
                return;
            }

            // 新規サブスク（FreeからのアップグレードはStripe Checkout）
            const res = await fetch('/api/create-checkout-session', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-User-ID': uid },
                body: JSON.stringify(params)
            });
            const data = await res.json();
            if (data.url) window.location.href = data.url;
            else alert(data.error || 'エラーが発生しました');
        } catch (e) { alert('通信エラー'); }
        finally { if (loadingOverlay) loadingOverlay.classList.add('hidden'); }
    }

    document.addEventListener('click', (e) => {
        const pBtn = e.target.closest('.btn-plan[data-plan]');
        if (pBtn) return handleCheckout({ plan: pBtn.getAttribute('data-plan') });
        const aBtn = e.target.closest('.btn-addon[data-addon]');
        if (aBtn) return handleCheckout({ addon: aBtn.getAttribute('data-addon') });
    });
});
