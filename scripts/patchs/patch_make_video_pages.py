FILE = 'scripts/make_video.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '''        for page_num, page_lines in enumerate(pages):
            png_path  = os.path.join(TMP_DIR, f"slide_{slide_counter:03d}.png")
            mp4_path  = os.path.join(TMP_DIR, f"slide_{slide_counter:03d}.mp4")
            aac_path  = os.path.join(TMP_DIR, f"audio_{slide_counter:03d}.aac")

            # Рендерим картинку
            render_slide(block, block_idx, total_slides,
                         page_lines, page_num, n_pages, png_path)
            print(f"  [SLIDE] стр.{page_num+1}/{n_pages}", end=" ")

            # Вырезаем нужный кусок аудио пропорционально символам
            page_sec = duration * chars_per_page[page_num] / total_chars
            start_sec = duration * sum(chars_per_page[:page_num]) / total_chars
            audio_for_slide = None
            if os.path.exists(mp3_path):
                ok = trim_audio(mp3_path, aac_path, start_sec, page_sec)
                if ok:
                    audio_for_slide = aac_path

            ok = make_slide_video(png_path, audio_for_slide, mp4_path,
                                  page_sec)
            if ok:
                all_mp4s.append(mp4_path)

            slide_counter += 1

            # Пауза между страницами (кроме последней)
            if page_num < n_pages - 1:
                time.sleep(1)

        # Пауза между блоками
        if block_idx < len(blocks) - 1:
            print(f"  [WAIT] Пауза 3 сек...")
            time.sleep(3)'''

NEW = '''        page_meta = block.get("pages", [])

        for page_num, page_lines in enumerate(pages):
            png_path = os.path.join(TMP_DIR, f"slide_{slide_counter:03d}.png")
            mp4_path = os.path.join(TMP_DIR, f"slide_{slide_counter:03d}.mp4")

            render_slide(block, block_idx, total_slides,
                         page_lines, page_num, n_pages, png_path)
            print(f"  [SLIDE] стр.{page_num+1}/{n_pages}", end=" ")

            # Берём готовый постраничный mp3
            audio_for_slide = None
            page_dur = 10
            if page_num < len(page_meta):
                pm = page_meta[page_num]
                candidate = os.path.join(BLOCKS_DIR, pm["filename"])
                if os.path.exists(candidate):
                    audio_for_slide = candidate
                    page_dur = pm.get("duration", 10)
            else:
                # Fallback: старый метод trim
                aac_path = os.path.join(TMP_DIR, f"audio_{slide_counter:03d}.aac")
                page_dur = duration * chars_per_page[page_num] / total_chars
                start_sec = duration * sum(chars_per_page[:page_num]) / total_chars
                if os.path.exists(mp3_path):
                    ok = trim_audio(mp3_path, aac_path, start_sec, page_dur)
                    if ok:
                        audio_for_slide = aac_path

            ok = make_slide_video(png_path, audio_for_slide, mp4_path, page_dur)
            if ok:
                all_mp4s.append(mp4_path)

            slide_counter += 1'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
