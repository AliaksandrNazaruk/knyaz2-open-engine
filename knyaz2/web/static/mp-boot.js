// Запуск опыта с соприсутствием. Живёт отдельным файлом, чтобы обычная игра
// его не грузила: всё различие между /index.html и /mp.html — эта строка.
import { presenceStart } from "./presence.js";

presenceStart();
