"""
画像処理モジュール
- 背景除去 (rembg)
- 手書き→フォトリアル変換 (OpenAI)
- 色調補正
- AI画像編集 (OpenAI)
"""
import io
import base64
from pathlib import Path

from PIL import Image, ImageFilter, ImageEnhance
import numpy as np


class ImageProcessor:

    # ──────────────────────────────────────────
    # 背景除去
    # ──────────────────────────────────────────
    @staticmethod
    def remove_background(pil_image: Image.Image) -> Image.Image:
        """rembg で背景を透明化"""
        from rembg import remove
        img_bytes = io.BytesIO()
        pil_image.save(img_bytes, format="PNG")
        img_bytes.seek(0)
        result_bytes = remove(img_bytes.getvalue())
        return Image.open(io.BytesIO(result_bytes)).convert("RGBA")

    # ──────────────────────────────────────────
    # 手書き → フォトリアル変換（OpenAI）
    # ──────────────────────────────────────────
    @staticmethod
    def sketch_to_realistic(
        pil_image: Image.Image,
        api_token: str,
        prompt: str = (
            "Transform this sketch into a 3D architectural model. "
            "3D rendering, photorealistic 3D visualization, CG, volumetric lighting, "
            "real building materials, concrete, glass, steel, sharp details, 8k resolution, "
            "NOT a painting, NOT a 2D illustration — a high-quality 3D rendered image."
        ),
    ) -> Image.Image:
        """
        OpenAI gpt-image-1 で手書きイラストをフォトリアルに変換
        """
        from openai import OpenAI

        client = OpenAI(api_key=api_token)

        buf = io.BytesIO()
        pil_image.convert("RGBA").save(buf, format="PNG")
        buf.seek(0)

        response = client.images.edit(
            model="gpt-image-1",
            image=("image.png", buf, "image/png"),
            prompt=prompt,
            size="1024x1024",
            quality="high",
            n=1,
        )

        img_data = base64.b64decode(response.data[0].b64_json)
        return Image.open(io.BytesIO(img_data)).convert("RGBA")

    # ──────────────────────────────────────────
    # 色調補正（背景に馴染ませる）
    # ──────────────────────────────────────────
    @staticmethod
    def match_color_tone(
        building: Image.Image,
        background: Image.Image,
        strength: float = 0.3,
    ) -> Image.Image:
        """
        建物画像の色調を背景に少し近づける
        strength: 0.0（変化なし）〜 1.0（完全マッチ）
        """
        bg_arr = np.array(background.convert("RGB")).astype(float)
        bg_mean = bg_arr.mean(axis=(0, 1))  # [R, G, B]

        bld = building.convert("RGBA")
        arr = np.array(bld).astype(float)
        bld_mean = arr[:, :, :3].mean(axis=(0, 1))

        shift = (bg_mean - bld_mean) * strength
        arr[:, :, 0] = np.clip(arr[:, :, 0] + shift[0], 0, 255)
        arr[:, :, 1] = np.clip(arr[:, :, 1] + shift[1], 0, 255)
        arr[:, :, 2] = np.clip(arr[:, :, 2] + shift[2], 0, 255)

        return Image.fromarray(arr.astype(np.uint8), "RGBA")

    # ──────────────────────────────────────────
    # 画像読み込み
    # ──────────────────────────────────────────
    @staticmethod
    def load_image(path: str) -> Image.Image:
        return Image.open(path).convert("RGBA")

    # ──────────────────────────────────────────
    # マスク指定による消去（ローカル OpenCV）
    # ──────────────────────────────────────────
    @staticmethod
    def inpaint_erase_local(
        pil_image: Image.Image,
        mask: Image.Image,
    ) -> Image.Image:
        """
        OpenCV の TELEA アルゴリズムでマスク領域を周囲のピクセルで埋める
        """
        import cv2

        img_rgb = np.array(pil_image.convert("RGB"))
        mask_np = np.array(mask.convert("L"))

        kernel = np.ones((5, 5), np.uint8)
        mask_dilated = cv2.dilate(mask_np, kernel, iterations=2)

        result = cv2.inpaint(
            img_rgb, mask_dilated,
            inpaintRadius=5,
            flags=cv2.INPAINT_TELEA,
        )
        return Image.fromarray(result).convert("RGBA")

    # ──────────────────────────────────────────
    # マスク指定による消去（OpenAI）
    # ──────────────────────────────────────────
    @staticmethod
    def inpaint_erase_ai(
        pil_image: Image.Image,
        mask: Image.Image,
        api_token: str,
    ) -> Image.Image:
        """
        OpenAI gpt-image-1 でマスク領域をAI補完
        mask: 白=消去対象、黒=保持
        """
        from openai import OpenAI

        client = OpenAI(api_key=api_token)

        img = pil_image.convert("RGB")
        max_size = 1024
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        target_size = img.size

        msk = mask.convert("L").resize(target_size, Image.Resampling.LANCZOS)

        # OpenAI mask: transparent(alpha=0) = 編集エリア、opaque = 保持エリア
        mask_arr = np.array(msk)
        rgba_arr = np.zeros((mask_arr.shape[0], mask_arr.shape[1], 4), dtype=np.uint8)
        rgba_arr[:, :, 3] = np.where(mask_arr > 128, 0, 255)
        openai_mask = Image.fromarray(rgba_arr, "RGBA")

        img_buf = io.BytesIO()
        img.save(img_buf, format="PNG")
        img_buf.seek(0)

        mask_buf = io.BytesIO()
        openai_mask.save(mask_buf, format="PNG")
        mask_buf.seek(0)

        response = client.images.edit(
            model="gpt-image-1",
            image=("image.png", img_buf, "image/png"),
            mask=("mask.png", mask_buf, "image/png"),
            prompt="empty sky, clean background, natural scenery, seamless continuation",
            size="1024x1024",
            n=1,
        )

        img_data = base64.b64decode(response.data[0].b64_json)
        return Image.open(io.BytesIO(img_data)).convert("RGBA")

    # ──────────────────────────────────────────
    # テキスト指示による画像編集（OpenAI）
    # ──────────────────────────────────────────
    @staticmethod
    def edit_by_instruction(
        pil_image: Image.Image,
        instruction: str,
        api_token: str,
    ) -> Image.Image:
        """
        OpenAI gpt-image-1 でテキスト指示により画像を編集
        """
        from openai import OpenAI

        client = OpenAI(api_key=api_token)

        rgb_image = pil_image.convert("RGB")
        max_size = 1024
        if rgb_image.width > max_size or rgb_image.height > max_size:
            rgb_image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        rgb_image.save(buf, format="PNG")
        buf.seek(0)

        response = client.images.edit(
            model="gpt-image-1",
            image=("image.png", buf, "image/png"),
            prompt=instruction,
            size="1024x1024",
            n=1,
        )

        img_data = base64.b64decode(response.data[0].b64_json)
        return Image.open(io.BytesIO(img_data)).convert("RGBA")

    # ──────────────────────────────────────────
    # 建物を背景に馴染ませる（ポアソンブレンディング → OpenAI で仕上げ）
    # ──────────────────────────────────────────
    @staticmethod
    def blend_building(
        background: Image.Image,
        building: Image.Image,
        center_x: int,
        center_y: int,
        width: int,
        height: int,
        angle: float = 0.0,
        api_token: str = "",
    ) -> Image.Image:
        """
        建物画像を背景に合成し、OpenAI でリアルな画像に仕上げる。
        center_x/y は背景画像座標系でのビルの中心位置。
        """
        import cv2

        bg_rgb = np.array(background.convert("RGB"))
        bg_h, bg_w = bg_rgb.shape[:2]

        # ── 建物をリサイズ ──
        bld = building.convert("RGBA").resize(
            (max(1, width), max(1, height)), Image.Resampling.LANCZOS
        )

        # ── 回転 ──
        if abs(angle) > 0.5:
            bld = bld.rotate(-angle, expand=True, resample=Image.Resampling.BICUBIC)

        bld_arr = np.array(bld)
        bld_rgb = bld_arr[:, :, :3]
        alpha = bld_arr[:, :, 3]
        bh, bw = bld_rgb.shape[:2]

        # ── マスク（白=建物がある部分） ──
        mask = np.zeros((bh, bw), dtype=np.uint8)
        mask[alpha > 10] = 255

        # ── 背景輝度に合わせて建物を補正 ──
        cx, cy = int(center_x), int(center_y)
        x1 = max(0, cx - bw // 2)
        y1 = max(0, cy - bh // 2)
        x2 = min(bg_w, x1 + bw)
        y2 = min(bg_h, y1 + bh)

        if x2 <= x1 or y2 <= y1:
            return background.convert("RGBA")

        bg_region = bg_rgb[y1:y2, x1:x2].astype(float)
        bld_region = bld_rgb[:y2-y1, :x2-x1].astype(float)
        region_mask = mask[:y2-y1, :x2-x1]

        if region_mask.sum() > 0:
            bg_mean = bg_region[region_mask > 0].mean()
            bld_mean = bld_region[region_mask > 0].mean()
            if bld_mean > 0:
                ratio = np.clip(bg_mean / bld_mean, 0.3, 3.0)
                bld_rgb = np.clip(bld_rgb.astype(float) * ratio, 0, 255).astype(np.uint8)

        # ── ポアソンブレンディング（境界チェック） ──
        margin = 5
        safe = (
            cx - bw // 2 >= margin and
            cy - bh // 2 >= margin and
            cx + bw // 2 <= bg_w - margin and
            cy + bh // 2 <= bg_h - margin
        )

        if safe and mask.sum() > 100:
            try:
                rough_rgb = cv2.seamlessClone(
                    bld_rgb, bg_rgb, mask,
                    (cx, cy),
                    cv2.NORMAL_CLONE,
                )
                rough = Image.fromarray(rough_rgb).convert("RGBA")
            except Exception:
                rough = None
        else:
            rough = None

        if rough is None:
            # フォールバック：通常アルファ合成
            rough = background.convert("RGBA").copy()
            bld_paste = Image.fromarray(bld_arr).convert("RGBA")
            rough.paste(bld_paste, (cx - bw // 2, cy - bh // 2), bld_paste)

        # ── OpenAI でリアルに仕上げ ──
        if api_token:
            from openai import OpenAI
            client = OpenAI(api_key=api_token)

            buf = io.BytesIO()
            rough.convert("RGB").save(buf, format="PNG")
            buf.seek(0)

            response = client.images.edit(
                model="gpt-image-1",
                image=("image.png", buf, "image/png"),
                prompt="これは雑に合成した写真です。合成したとは思えないリアルな写真を生成してください。絵画的・イラスト的にならないようにしてください。本物の写真のようにしてください。",
                size="1024x1024",
                quality="high",
                n=1,
            )

            img_data = base64.b64decode(response.data[0].b64_json)
            return Image.open(io.BytesIO(img_data)).convert("RGBA")

        return rough

    # ──────────────────────────────────────────
    # 手書き判定（簡易）
    # ──────────────────────────────────────────
    @staticmethod
    def is_sketch(pil_image: Image.Image) -> bool:
        """
        グレースケールに変換し、ピクセルの分布が
        白黒 2 極化していれば手書きとみなす（簡易判定）
        """
        gray = np.array(pil_image.convert("L")).astype(float)
        ratio_dark = (gray < 30).sum() / gray.size
        ratio_light = (gray > 225).sum() / gray.size
        return (ratio_dark + ratio_light) > 0.6
