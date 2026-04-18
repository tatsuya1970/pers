document.addEventListener('DOMContentLoaded', () => {
    // --- UI要素 ---
    const wrapper = document.getElementById('canvas-wrapper');
    const statusMsg = document.querySelector('.status-msg');

    // --- ロギング（コンソール出力へ変更） ---
    function addLog(msg, type = 'info') {
        const time = new Date().toLocaleTimeString('ja-JP', { hour12: false });
        const logMsg = `[${time}] [${type.toUpperCase()}] ${msg}`;
        if (type === 'error') {
            console.error(logMsg);
        } else if (type === 'warn') {
            console.warn(logMsg);
        } else {
            console.log(logMsg);
        }
    }

    const loadingOverlay = document.getElementById('loading-overlay');
    const clickBlocker = document.getElementById('click-blocker');

    function setControlsDisabled(disabled) {
        document.querySelectorAll('button, input, textarea').forEach(el => {
            el.disabled = disabled;
        });
        if (disabled) {
            clickBlocker.classList.add('active');
        } else {
            clickBlocker.classList.remove('active');
        }
    }

    // データURLをBlobに変換するヘルパー
    const dataUrlToBlob = async (url) => (await fetch(url)).blob();

    // --- Fabric.js キャンバス初期化 ---
    // wrapperのサイズに合わせて初期化（背景アップロード時にリサイズします）
    const fCanvas = new fabric.Canvas('main-canvas', {
        preserveObjectStacking: true,
        selection: false // 範囲選択を無効化し、オブジェクト個別の選択のみ許容
    });

    fCanvas.setWidth(wrapper.clientWidth * 0.9);
    fCanvas.setHeight(wrapper.clientHeight * 0.9);

    let originalBgBlob = null; // 背景のアップロード状態を保持

    // --- 背景アップロード ---
    const bgInput = document.getElementById('bg-input');
    document.getElementById('open-bg-btn').addEventListener('click', () => bgInput.click());

    bgInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) handleBackground(e.target.files[0]);
    });

    async function handleBackground(file) {
        addLog(`背景画像を読み込み中...`, 'info');
        originalBgBlob = file; // 保持
        const reader = new FileReader();
        reader.onload = (e) => setBackgroundFromURL(e.target.result, true);
        reader.readAsDataURL(file);
    }

    function setBackgroundFromURL(dataUrl, isNewUpload = false) {
        fabric.Image.fromURL(dataUrl, (img) => {
            // Fabric.jsのZoom機能を使って、マウスクリックなどの座標計算を保ったまま見た目を縮小
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

            if (isNewUpload) {
                fCanvas.getObjects().forEach(obj => fCanvas.remove(obj));
                canvasHistory = []; // 新たな背景で履歴リセット
            }

            // 背景を設定
            fCanvas.setBackgroundImage(img, () => {
                fCanvas.renderAll();
                saveHistory(); // 背景の描画完了後に履歴保存
                if (isNewUpload) addLog('背景画像を設定しました。', 'info');
            }, {
                originX: 'left',
                originY: 'top'
            });
        });
    }

    // --- 通常の建物追加（写真・CG） ---
    const photoInput = document.createElement('input');
    photoInput.type = 'file';
    photoInput.accept = 'image/*';
    photoInput.style.display = 'none';
    document.body.appendChild(photoInput);
    document.getElementById('add-photo-btn').addEventListener('click', () => photoInput.click());

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace' || e.key === 'Delete') {
            const activeObj = fCanvas.getActiveObject();
            if (activeObj && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
                fCanvas.remove(activeObj);
                addLog('オブジェクトを削除しました。', 'info');
                saveHistory();
            }
        }
    });

    photoInput.addEventListener('change', async (e) => {
        if (e.target.files.length > 0) {
            if (!fCanvas.backgroundImage) {
                addLog('先に背景画像をアップロードしてください。', 'warn');
                return;
            }

            const file = e.target.files[0];
            const matchColor = document.getElementById('match-color').checked;

            let imageUrl = '';
            if (matchColor) {
                setControlsDisabled(true);
                loadingOverlay.querySelector('p').textContent = '色調を補正中...';
                loadingOverlay.classList.remove('hidden');
                addLog('背景に合わせて建物の色調を補正中...', 'info');
                const formData = new FormData();
                const currentBgBlob = await dataUrlToBlob(fCanvas.toDataURL({ format: 'png', multiplier: 1 / fCanvas.getZoom() }));
                formData.append('bg_file', currentBgBlob, 'bg.png');
                formData.append('bld_file', file);

                const uid = window.currentUserUID;
                try {
                    const res = await fetch('/api/match-color', {
                        method: 'POST',
                        body: formData,
                        headers: uid ? { 'X-User-ID': uid } : {}
                    });
                    const data = await res.json();
                    if (data.error) throw new Error(data.error);
                    imageUrl = data.image_base64;
                } catch (err) {
                    addLog('エラー: ' + err.message, 'error');
                    alert(err.message);
                } finally {
                    setControlsDisabled(false);
                    loadingOverlay.classList.add('hidden');
                    loadingOverlay.querySelector('p').textContent = '背景に馴染ませ中...';
                }
            }

            if (!imageUrl) {
                imageUrl = await new Promise(resolve => {
                    const reader = new FileReader();
                    reader.onload = (ev) => resolve(ev.target.result);
                    reader.readAsDataURL(file);
                });
            }

            fabric.Image.fromURL(imageUrl, (img) => {
                const logicalWidth = fCanvas.getWidth() / fCanvas.getZoom();
                const logicalHeight = fCanvas.getHeight() / fCanvas.getZoom();
                img.set({
                    left: logicalWidth / 2,
                    top: logicalHeight / 2,
                    originX: 'center',
                    originY: 'center',
                    cornerColor: '#3b82f6',
                    transparentCorners: false
                });
                if (img.width > logicalWidth * 0.5) {
                    img.scaleToWidth(logicalWidth * 0.5);
                }
                fCanvas.add(img);
                fCanvas.setActiveObject(img);
                addLog('建物を追加しました。ドラッグ移動・拡大縮小・回転が可能です！', 'info');
                saveHistory();
            });

            photoInput.value = '';
        }
    });

    // --- 手書きイラストAI変換 ---
    const sketchBtn = document.getElementById('add-sketch-btn');
    const sketchInput = document.createElement('input');
    sketchInput.type = 'file';
    sketchInput.accept = 'image/*';
    sketchInput.style.display = 'none';
    document.body.appendChild(sketchInput);
    sketchBtn.addEventListener('click', () => sketchInput.click());

    sketchInput.addEventListener('change', async (e) => {
        if (e.target.files.length > 0) {
            if (!fCanvas.backgroundImage) {
                addLog('先に背景画像をアップロードしてください。', 'warn');
                return;
            }

            const file = e.target.files[0];

            // 手書きの絵をそのままキャンバスに配置する（変換はまだしない）
            const reader = new FileReader();
            reader.onload = (event) => {
                fabric.Image.fromURL(event.target.result, (img) => {
                    const logicalWidth = fCanvas.getWidth() / fCanvas.getZoom();
                    const logicalHeight = fCanvas.getHeight() / fCanvas.getZoom();
                    img.set({
                        left: logicalWidth / 2,
                        top: logicalHeight / 2,
                        originX: 'center',
                        originY: 'center',
                        cornerColor: '#f59e0b', // 手書きなのでオレンジ色っぽく
                        transparentCorners: false,
                        opacity: 0.9
                    });
                    if (img.width > logicalWidth * 0.5) {
                        img.scaleToWidth(logicalWidth * 0.5);
                    }
                    // カスタムプロパティとして手書きレイヤーであることを保持
                    img.isSketchLayer = true;

                    fCanvas.add(img);
                    fCanvas.setActiveObject(img);
                    addLog('手書きイラストを配置しました。「背景に馴染ませる」を押すとAI変換と合成が同時に走ります。', 'info');
                    saveHistory();
                });
            };
            reader.readAsDataURL(file);
            sketchInput.value = '';
        }
    });

    // --- 背景に馴染ませる (Blend) ---
    const blendBtn = document.getElementById('blend-btn');
    blendBtn.addEventListener('click', async () => {
        const obj = fCanvas.getActiveObject();
        if (!obj) { addLog('合成する建物（レイヤー）を選択状態でクリックしてください。', 'warn'); return; }
        if (!fCanvas.backgroundImage) { addLog('背景が設定されていません。', 'warn'); return; }

        setControlsDisabled(true);
        loadingOverlay.querySelector('p').textContent = '背景に馴染ませ中...';
        loadingOverlay.classList.remove('hidden');
        addLog('馴染ませ処理を実行中（OpenAIによる仕上げ）...', 'info');

        try {
            // 背景は非圧縮のアップロードされた元データを送信
            // もし何らかの加工が入っていたら dataURL からBlobを作る必要がありますが、ここではオリジナルを使用

            // 建物のオブジェクトを単体でラスタライズ（座標などはそのまま送る）
            const objData = obj.toDataURL({ format: 'png', multiplier: 1 }); // 元サイズ比
            const objBlob = await dataUrlToBlob(objData);

            // Fabricからの座標とサイズを取得
            const cx = obj.left;
            const cy = obj.top;
            const scaledWidth = obj.getScaledWidth();
            const scaledHeight = obj.getScaledHeight();
            const angle = obj.angle;

            const formData = new FormData();

            // 重要：背景画像としてキャプチャする前に、現在馴染ませようとしている建物の表示を消す！
            // そうしないと「すでに建物が乗っている背景」に対してさらに合成処理がかかり、変化が起きなくなります。
            obj.set('visible', false);
            fCanvas.discardActiveObject();
            fCanvas.renderAll();

            // ズームの影響を受けない元の高解像度サイズでキャプチャする
            const multiplier = 1 / fCanvas.getZoom();
            const currentBgBlob = await dataUrlToBlob(fCanvas.toDataURL({ format: 'png', multiplier: multiplier }));

            // 元に戻す
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

            // 手書きレイヤーの場合はフラグを付ける
            if (obj.isSketchLayer) {
                formData.append('is_sketch', 'true');
            } else {
                formData.append('is_sketch', 'false');
            }

            const uid = window.currentUserUID;
            const res = await fetch('/api/blend', {
                method: 'POST',
                body: formData,
                headers: uid ? { 'X-User-ID': uid } : {}
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);

            if (data.credits_remaining !== undefined) {
                const cd = document.getElementById('credit-display');
                if (cd) cd.textContent = `チケット残高: ${data.credits_remaining}`;
            }

            setBackgroundFromURL(data.image_base64, false);
            fCanvas.remove(obj);
            addLog('馴染ませ完了！建物が背景と一体化しました。', 'info');
        } catch (err) {
            addLog('エラー: ' + err.message, 'error');
            if (err.message.includes('チケット残高が不足しています')) {
                if (confirm('チケット残高が不足しています。10枚追加（1000円）しますか？')) {
                    const uid = window.currentUserUID;
                    fetch('/api/create-checkout-session', {
                        method: 'POST',
                        headers: uid ? { 'X-User-ID': uid } : {}
                    })
                    .then(res => res.json())
                    .then(data => {
                        if (data.url) {
                            window.location.href = data.url;
                        } else {
                            alert('決済セッションの作成に失敗しました: ' + (data.error || '不明なエラー'));
                        }
                    })
                    .catch(e => alert('通信エラーが発生しました'));
                }
            } else {
                alert(err.message);
            }
        } finally {
            setControlsDisabled(false);
            loadingOverlay.classList.add('hidden');
        }
    });

    // --- 指示を実行 ---
    const instructBtn = document.getElementById('ai-instruct-btn');
    const instructInput = document.querySelector('.textarea');
    instructBtn.addEventListener('click', async () => {
        const text = instructInput.value.trim();
        if (!text) { addLog('指示を入力してください。', 'warn'); return; }
        if (!fCanvas.backgroundImage) return;

        setControlsDisabled(true);
        loadingOverlay.querySelector('p').textContent = 'AIによる指示を実行中...';
        loadingOverlay.classList.remove('hidden');
        addLog(`AIへのテキスト指示を実行中: "${text}"`, 'info');

        try {
            fCanvas.discardActiveObject(); // 選択解除して綺麗なプレビューに
            fCanvas.renderAll();

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

            if (data.credits_remaining !== undefined) {
                const cd = document.getElementById('credit-display');
                if (cd) cd.textContent = `チケット残高: ${data.credits_remaining}`;
            }

            setBackgroundFromURL(data.image_base64, false);
            fCanvas.clear(); // 全レイヤー削除
            addLog('AI編集が完了しました！', 'info');
        } catch (err) {
            addLog('エラー: ' + err.message, 'error');
            if (err.message.includes('チケット残高が不足しています')) {
                if (confirm('チケット残高が不足しています。10枚追加（1000円）しますか？')) {
                    buyCredits();
                }
            } else {
                alert(err.message);
            }
        } finally {
            setControlsDisabled(false);
            loadingOverlay.classList.add('hidden');
            loadingOverlay.querySelector('p').textContent = '背景に馴染ませ中...';
            instructInput.value = '';
        }
    });

    // --- Undo (履歴) 機能 ---
    let canvasHistory = [];
    let isUndoing = false;
    const undoBtn = document.getElementById('undo-btn');

    function saveHistory() {
        if (isUndoing) return;
        const state = JSON.stringify(fCanvas.toJSON(['isSketchLayer']));
        canvasHistory.push(state);
        // 最大履歴数20
        if (canvasHistory.length > 20) canvasHistory.shift();
        if (undoBtn) undoBtn.disabled = (canvasHistory.length <= 1);
    }

    if (undoBtn) {
        undoBtn.addEventListener('click', () => {
            if (canvasHistory.length <= 1) return;
            isUndoing = true;
            canvasHistory.pop(); // 最新状態を破棄
            const prevState = canvasHistory[canvasHistory.length - 1]; // 1つ前を取得

            fCanvas.loadFromJSON(prevState, () => {
                fCanvas.renderAll();
                isUndoing = false;
                undoBtn.disabled = (canvasHistory.length <= 1);
                addLog('一つ前の状態に戻しました。', 'info');

                // ズーム設定を再適用
                if (fCanvas.backgroundImage) {
                    const img = fCanvas.backgroundImage;
                    const scale = Math.min(
                        (wrapper.clientWidth * 0.9) / (img.width || img.getOriginalSize().width),
                        (wrapper.clientHeight * 0.9) / (img.height || img.getOriginalSize().height)
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
            });
        });
    }

    fCanvas.on('object:modified', saveHistory); // 移動・拡大縮小・回転の終了時に保存

    // --- PNG で書き出し ---
    const exportBtn = document.getElementById('export-btn');
    exportBtn.addEventListener('click', () => {
        if (!fCanvas.backgroundImage) {
            addLog('エクスポートする画像がありません。', 'warn');
            return;
        }

        fCanvas.discardActiveObject();
        fCanvas.renderAll();

        const multiplier = 1 / fCanvas.getZoom();
        const dataURL = fCanvas.toDataURL({ format: 'png', multiplier: multiplier });

        const link = document.createElement('a');
        link.download = 'パース合成_エクスポート.png';
        link.href = dataURL;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        addLog('画像を書き出しました。', 'info');
    });

    // --- ギャラリー (履歴) 機能 ---
    const galleryOverlay = document.getElementById('gallery-overlay');
    const openGalleryBtn = document.getElementById('open-gallery-btn');
    const closeGalleryBtn = document.getElementById('close-gallery-btn');
    const galleryGrid = document.getElementById('gallery-grid');

    openGalleryBtn.addEventListener('click', async () => {
        galleryOverlay.style.display = 'flex';
        galleryGrid.innerHTML = '<p style="color: #aaa; text-align: center; grid-column: 1 / -1;">読み込み中...</p>';

        try {
            const uid = window.currentUserUID;
            const res = await fetch('/api/gallery', {
                method: 'GET',
                headers: uid ? { 'X-User-ID': uid } : {}
            });
            const data = await res.json();

            if (data.status !== "success") throw new Error(data.error);

            galleryGrid.innerHTML = '';
            if (!data.images || data.images.length === 0) {
                galleryGrid.innerHTML = '<p style="color: #aaa; text-align: center; grid-column: 1 / -1;">まだ作成された画像がありません。</p>';
                return;
            }

            data.images.forEach(imgData => {
                const card = document.createElement('div');
                card.style.background = '#222';
                card.style.borderRadius = '8px';
                card.style.overflow = 'hidden';
                card.style.border = '1px solid var(--border-color)';
                card.style.display = 'flex';
                card.style.flexDirection = 'column';

                // 表示用画像
                const img = document.createElement('img');
                img.src = imgData.url;
                img.style.width = '100%';
                img.style.height = '160px';
                img.style.objectFit = 'cover';
                img.style.borderBottom = '1px solid var(--border-color)';

                // 日付
                const d = new Date(imgData.created_at);
                const dateStr = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

                const uiBox = document.createElement('div');
                uiBox.style.padding = '12px';
                uiBox.style.display = 'flex';
                uiBox.style.flexDirection = 'column';
                uiBox.style.gap = '8px';

                const dateEl = document.createElement('span');
                dateEl.textContent = dateStr;
                dateEl.style.fontSize = '0.75rem';
                dateEl.style.color = '#888';

                const dlBtn = document.createElement('a');
                dlBtn.href = imgData.url;
                dlBtn.download = `合成パース_${dateStr}.png`;
                dlBtn.className = 'btn btn-outline-green';
                dlBtn.style.padding = '4px';
                dlBtn.style.fontSize = '0.75rem';
                dlBtn.style.textAlign = 'center';
                dlBtn.innerHTML = 'ダウンロード';

                // 削除ボタン
                const delBtn = document.createElement('button');
                delBtn.className = 'btn';
                delBtn.style.padding = '4px';
                delBtn.style.fontSize = '0.75rem';
                delBtn.style.backgroundColor = 'transparent';
                delBtn.style.color = '#ef4444';
                delBtn.style.border = '1px solid #ef4444';
                delBtn.style.width = '100%';
                delBtn.innerHTML = '削除';

                delBtn.addEventListener('click', async () => {
                    if (!confirm('この画像を削除してもよろしいですか？')) return;
                    try {
                        const uid = window.currentUserUID;
                        const delRes = await fetch(`/api/gallery/${imgData.id}`, {
                            method: 'DELETE',
                            headers: uid ? { 'X-User-ID': uid } : {}
                        });
                        const delData = await delRes.json();
                        if (delData.status === "success") {
                            card.remove();
                            // もしすべて削除されたらメッセージを表示
                            if (galleryGrid.children.length === 0) {
                                galleryGrid.innerHTML = '<p style="color: #aaa; text-align: center; grid-column: 1 / -1;">まだ作成された画像がありません。</p>';
                            }
                        } else {
                            alert(delData.error || '削除に失敗しました');
                        }
                    } catch (e) {
                        alert('エラーが発生しました: ' + e.message);
                    }
                });

                uiBox.appendChild(dateEl);
                uiBox.appendChild(dlBtn);
                uiBox.appendChild(delBtn);

                card.appendChild(img);
                card.appendChild(uiBox);
                galleryGrid.appendChild(card);
            });

        } catch (err) {
            galleryGrid.innerHTML = `<p style="color: red; text-align: center; grid-column: 1 / -1;">エラー: ${err.message}</p>`;
        }
    });

    closeGalleryBtn.addEventListener('click', () => {
        galleryOverlay.style.display = 'none';
    });

    // --- 料金プランモーダル制御 (閉じ処理のみ維持、開き処理は index.html へ集約) ---
    const pricingModal = document.getElementById('pricing-modal');
    const closePricingBtn = document.getElementById('close-pricing-btn');

    if (closePricingBtn && pricingModal) {
        closePricingBtn.addEventListener('click', () => {
            pricingModal.classList.add('hidden');
        });
    }

    if (pricingModal) {
        pricingModal.addEventListener('click', (e) => {
            if (e.target === pricingModal) {
                pricingModal.classList.add('hidden');
            }
        });
    }

    // 決済・プランアップグレードのコアロジック
    async function handleCheckout(params) {
        const userUID = window.currentUserUID;
        if (!userUID) {
            alert('ログインが必要です。Googleでログインしてから再度お試しください。');
            return;
        }

        try {
            // ローディングを表示
            document.getElementById('loading-overlay')?.classList.remove('hidden');

            const response = await fetch('/api/create-checkout-session', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-User-ID': userUID
                },
                body: JSON.stringify(params)
            });

            const data = await response.json();
            if (data.url) {
                window.location.href = data.url;
            } else {
                document.getElementById('loading-overlay')?.classList.add('hidden');
                alert('エラー: ' + (data.error || '決済セッションの作成に失敗しました'));
            }
        } catch (error) {
            document.getElementById('loading-overlay')?.classList.add('hidden');
            console.error('Checkout error:', error);
            alert('通信エラーが発生しました');
        }
    }

    // イベント委譲（要素が動的に変わっても反応するようにする）
    document.addEventListener('click', (e) => {
        const planBtn = e.target.closest('.btn-plan[data-plan]');
        if (planBtn) {
            handleCheckout({ plan: planBtn.getAttribute('data-plan') });
            return;
        }

        const addonBtn = e.target.closest('.btn-addon[data-addon]');
        if (addonBtn) {
            handleCheckout({ addon: addonBtn.getAttribute('data-addon') });
            return;
        }
    });
});
