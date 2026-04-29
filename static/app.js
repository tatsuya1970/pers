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

        if (addPhotoBtn) addPhotoBtn.disabled = !hasBg;
        if (addSketchBtn) addSketchBtn.disabled = !hasBg;
        if (instructBtn) instructBtn.disabled = !hasBg;
        if (instructInput) instructInput.disabled = !hasBg;
        if (exportBtn) exportBtn.disabled = !hasBg;
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
        addPhotoBtn.addEventListener('click', () => photoInput.click());
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
        sketchBtn.addEventListener('click', () => sketchInput.click());
    }

    sketchInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
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

                const formData = new FormData();
                formData.append('file', blob, 'canvas.png');
                formData.append('instruction', text);

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
            });
        });
    }
    fCanvas.on('object:modified', saveHistory);

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

    // --- ギャラリー ---
    const openGalleryBtn = document.getElementById('open-gallery-btn');
    const closeGalleryBtn = document.getElementById('close-gallery-btn');
    const galleryOverlay = document.getElementById('gallery-overlay');
    const galleryGrid = document.getElementById('gallery-grid');

    if (openGalleryBtn && galleryOverlay) {
        openGalleryBtn.addEventListener('click', async () => {
            galleryOverlay.classList.remove('hidden');
            galleryOverlay.style.display = 'flex';
            if (galleryGrid) galleryGrid.innerHTML = '読み込み中...';
            try {
                const uid = window.currentUserUID;
                const res = await fetch('/api/gallery', { headers: uid ? { 'X-User-ID': uid } : {} });
                const data = await res.json();
                if (galleryGrid) {
                    galleryGrid.innerHTML = '';
                    data.images?.forEach(imgData => {
                        const img = document.createElement('img');
                        img.src = imgData.url;
                        img.style.width = '100px'; // 簡易表示
                        galleryGrid.appendChild(img);
                    });
                }
            } catch (e) { console.error(e); }
        });
    }
    if (closeGalleryBtn && galleryOverlay) {
        closeGalleryBtn.addEventListener('click', () => {
            galleryOverlay.style.display = 'none';
        });
    }

    // --- 決済ロジック ---
    async function handleCheckout(params) {
        const uid = window.currentUserUID;
        if (!uid) { alert('ログインが必要です。'); return; }
        try {
            if (loadingOverlay) loadingOverlay.classList.remove('hidden');
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
