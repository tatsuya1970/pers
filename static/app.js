document.addEventListener('DOMContentLoaded', () => {
    // --- UI要素 ---
    const wrapper = document.getElementById('canvas-wrapper');
    const workspace = document.getElementById('canvas-workspace');
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
        if (blendBtn) blendBtn.disabled = !hasBg;
        if (clearBtn) clearBtn.disabled = !hasBg && fCanvas.getObjects().length === 0;
    }
    updateFeatureButtonsState();

    let originalBgBlob = null;

    // 背景セットヘルパー
    function setBackgroundFromURL(url, updateCanvasSize = false) {
        // ステータスメッセージを即座に消す
        const statusMsg = document.getElementById('status-msg');
        if (statusMsg) statusMsg.textContent = '';

        fabric.Image.fromURL(url, (img) => {
            if (updateCanvasSize && wrapper) {
                const scale = Math.min(
                    (wrapper.clientWidth * 0.9) / img.width,
                    (wrapper.clientHeight * 0.9) / img.height
                );
                // 常にスケールを適用（小さい画像は拡大、大きい画像は縮小して枠に収める）
                fCanvas.setZoom(scale);
                fCanvas.setWidth(img.width * scale);
                fCanvas.setHeight(img.height * scale);
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
            e.target.value = '';
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
        } else if (!fCanvas.backgroundImage && e.target.files.length > 0) {
            alert('先に背景をアップロードしてください。');
        }
        e.target.value = '';
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
        e.target.value = '';
    });

    // --- 背景に馴染ませる ---
    const blendBtn = document.getElementById('blend-btn');
    if (blendBtn) {
        blendBtn.addEventListener('click', async () => {
            const obj = fCanvas.getActiveObject();
            if (!obj) { 
                addLog('合成する建物（レイヤー）を選択状態でクリックしてください。', 'warn'); 
                alert('合成する建物（レイヤー）を選択状態でクリックしてください。');
                return; 
            }
            if (!fCanvas.backgroundImage) { addLog('背景が設定されていません。', 'warn'); return; }

            setControlsDisabled(true);
            if (loadingOverlay) {
                loadingOverlay.querySelector('p').textContent = '背景に合成中...';
                loadingOverlay.classList.remove('hidden');
            }
            addLog('合成処理を実行中...', 'info');

            try {
                const objData = obj.toDataURL({ format: 'png', multiplier: 1 });
                const objBlob = await dataUrlToBlob(objData);

                const cx = obj.left;
                const cy = obj.top;
                const scaledWidth = obj.getScaledWidth();
                const scaledHeight = obj.getScaledHeight();
                const angle = obj.angle;

                const formData = new FormData();

                obj.set('visible', false);
                fCanvas.discardActiveObject();
                fCanvas.renderAll();

                const multiplier = 1 / fCanvas.getZoom();
                const currentBgBlob = await dataUrlToBlob(fCanvas.toDataURL({ format: 'png', multiplier: multiplier }));

                obj.set('visible', true);
                fCanvas.setActiveObject(obj);
                fCanvas.renderAll();

                formData.append('bg_file', currentBgBlob, 'bg.png');
                formData.append('bld_file', objBlob, 'bld.png');
                formData.append('cx', cx);
                formData.append('cy', cy);
                formData.append('width', scaledWidth);
                formData.append('height', scaledHeight);
                formData.append('angle', angle);
                formData.append('is_sketch', obj.isSketchLayer ? 'true' : 'false');

                const uid = window.currentUserUID;
                const res = await fetch('/api/blend', {
                    method: 'POST',
                    body: formData,
                    headers: uid ? { 'X-User-ID': uid } : {}
                });
                const data = await res.json();
                if (data.error) throw new Error(data.error);

                if (data.credits_remaining !== undefined) {
                    const cd = document.getElementById('credit-count');
                    if (cd) cd.textContent = data.credits_remaining;
                }

                setBackgroundFromURL(data.image_base64, false);
                fCanvas.remove(obj);
                addLog('馴染ませ完了！建物が背景と一体化しました。', 'info');
            } catch (err) {
                addLog('エラー: ' + err.message, 'error');
                if (err.message.includes('チケット') || err.message.includes('クレジット')) {
                    if (confirm('クレジット残高が不足しています。購入画面を開きますか？')) {
                        const pricingModal = document.getElementById('pricing-modal');
                        if (pricingModal) pricingModal.classList.remove('hidden');
                    }
                } else {
                    alert('エラー: ' + err.message);
                }
            } finally {
                setControlsDisabled(false);
                if (loadingOverlay) {
                    loadingOverlay.classList.add('hidden');
                    loadingOverlay.querySelector('p').textContent = '処理中...';
                }
            }
        });
    }

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
                loadingOverlay.querySelector('p').textContent = '処理を実行中...';
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
        updateFeatureButtonsState();
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

    // --- クリア ---
    const clearBtn = document.getElementById('clear-btn');
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            if (!confirm('全ての写真と背景をクリアしてよろしいですか？')) return;
            
            fCanvas.clear();
            fCanvas.backgroundImage = null;
            
            // ズームと位置をリセット
            fCanvas.setZoom(1);
            fCanvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
            
            // キャンバスサイズを初期サイズに戻す
            if (wrapper) {
                fCanvas.setWidth(wrapper.clientWidth * 0.9);
                fCanvas.setHeight(wrapper.clientHeight * 0.9);
            }
            
            fCanvas.renderAll();
            
            originalBgBlob = null;
            canvasHistory = [];
            
            const statusMsg = document.getElementById('status-msg');
            if (statusMsg) statusMsg.textContent = '背景写真をアップロードしてください';
            
            saveHistory();
            updateFeatureButtonsState();
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
            // 元の解像度を維持、ただしズームアップしている場合は現在の表示サイズで出力
            const multiplier = Math.max(1, 1 / fCanvas.getZoom());
            link.href = fCanvas.toDataURL({ format: 'png', multiplier: multiplier });
            link.click();
        });
    }

    // --- ギャラリー (機能停止中) ---
    /*
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
    */

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

    // --- ドラッグ＆ドロップ ---
    if (workspace) {
        workspace.addEventListener('dragover', (e) => {
            e.preventDefault();
            workspace.classList.add('drag-over');
        });
        workspace.addEventListener('dragleave', () => {
            workspace.classList.remove('drag-over');
        });
        workspace.addEventListener('drop', (e) => {
            e.preventDefault();
            workspace.classList.remove('drag-over');
            if (e.dataTransfer.files.length > 0) {
                const file = e.dataTransfer.files[0];
                if (file.type.startsWith('image/')) {
                    if (!fCanvas.backgroundImage) {
                        originalBgBlob = file;
                        const reader = new FileReader();
                        reader.onload = (ev) => setBackgroundFromURL(ev.target.result, true);
                        reader.readAsDataURL(file);
                    } else {
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
                    }
                }
            }
        });
    }

    // 初期ステータス
    const statusMsg = document.getElementById('status-msg');
    if (statusMsg) statusMsg.textContent = '背景写真をアップロードしてください';
});
