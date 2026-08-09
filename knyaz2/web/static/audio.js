// Панель музыки: ручной селектор треков поверх ядра sound.js.
//
// Сама музыка карты стартует автоматически (soundscape.js, выбор трека —
// VA 0x437F48); эта панель — дев-инструмент: послушать любой из одиннадцати
// треков и выключить музыку вовсе (бинарная громкость, как 0x42D0E8).
import { audioToggleNode, audioTrackNode } from "./dom.js";
import { playMusic, setMusicOn, sound, stopMusic } from "./sound.js";

export function audioSetup(config) {
  if (audioTrackNode.options.length) {          // селектор общий на все карты
    markMapTrack(config?.map_track);
    return;
  }
  for (const track of config?.tracks ?? []) {
    const option = document.createElement("option");
    option.value = String(track.slot);
    option.textContent =
      `слот ${track.slot} · ${Math.round(track.seconds / 60)}:` +
      `${String(Math.round(track.seconds) % 60).padStart(2, "0")}`;
    audioTrackNode.append(option);
  }
  markMapTrack(config?.map_track);
}

function markMapTrack(slot) {
  for (const option of audioTrackNode.options) {
    const own = Number(option.value) === slot;
    option.textContent = option.textContent.replace(" · трек карты", "") +
      (own ? " · трек карты" : "");
    if (own) audioTrackNode.value = option.value;
  }
}

export function audioStop() {
  stopMusic();
  setMusicOn(false);
  sound.musicOverride = null;
  audioToggleNode.textContent = "▶ играть";
}

audioToggleNode.addEventListener("click", () => {
  if (sound.music) { audioStop(); return; }
  setMusicOn(true);
  sound.musicOverride = Number(audioTrackNode.value);
  playMusic(sound.musicOverride);
  audioToggleNode.textContent = "⏸ пауза";
});

audioTrackNode.addEventListener("change", () => {
  if (!sound.music) return;
  sound.musicOverride = Number(audioTrackNode.value);
  playMusic(sound.musicOverride);
});
