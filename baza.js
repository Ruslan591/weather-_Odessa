const importBtn = document.getElementById("importBtn");
const importFile = document.getElementById("importFile");

importBtn.addEventListener("click", () => {
    // Пробрасываем клик на скрытый input
    importFile.click();
});

importFile.addEventListener("change", async () => {
    if (!importFile.files.length) return;

    const file = importFile.files[0];
    const text = await file.text();

    try {
        const data = JSON.parse(text);

        if (!Array.isArray(data)) {
            alert("Неверный формат файла");
            return;
        }

        // Очистка старой базы и добавление новой
        const tx = db.transaction("stats", "readwrite");
        const store = tx.objectStore("stats");

        // Очистим старую базу
        const clearReq = store.clear();
        clearReq.onsuccess = () => {
            // Добавляем новые записи
            data.forEach(item => store.add(item));
            alert("База успешно восстановлена");
        };

        clearReq.onerror = e => {
            console.error("Ошибка очистки базы", e);
        };

    } catch (err) {
        alert("Ошибка при чтении файла");
        console.error(err);
    }
});