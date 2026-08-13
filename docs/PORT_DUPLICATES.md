# Дубли и самодеятельность в порте

Отчёт `tools/duplicates.py`. Различитель — ссылка на адрес движка: каждая перенесённая механика называет, откуда снята. Адрес, заявленный двумя функциями, — дубль; функция без единой ссылки — либо связка, либо выдуманное правило.

адресов заявлено: 149

заявлены дважды и более: 45

функций без единого адреса: 408 (крупнее 25 строк: 43)

## Один адрес — две реализации

| адрес | кто заявляет |
|---|---|
| `0x004107ec` | `knyaz2/web/static/warband.js::adjacentEnemy`, `knyaz2/web/static/warband.js::enemyFor` |
| `0x00410a08` | `knyaz2/web/static/orders.js::orderWaitTalk`, `knyaz2/web/static/sfx.js::sfxTalkRequest` |
| `0x004115ac` | `knyaz2/web/static/combat.js::openBody`, `knyaz2/web/static/combat.js::unitArrived`, `knyaz2/web/static/jewels.js::identifyRoll`, `knyaz2/web/static/orders.js::withinTalk` |
| `0x0041209c` | `knyaz2/web/static/orders.js::followDistance`, `knyaz2/web/static/units.js::formationSpot` |
| `0x00413110` | `knyaz2/web/static/progress.js::grantExperience`, `knyaz2/web/static/sfx.js::sfxLevelUp` |
| `0x004131fc` | `knyaz2/web/static/effects.js::expireTemporary`, `knyaz2/web/static/progress.js::progressLocked` |
| `0x00413894` | `knyaz2/web/static/combat.js::killReward`, `knyaz2/web/static/hero.js::unitUpdateBuilding`, `knyaz2/web/static/units.js::isShootingPose`, `knyaz2/web/static/units.js::strikeLands`, `knyaz2/web/static/units.js::talkingWith`, `knyaz2/web/static/units.js::waitTalkTick`, `knyaz2/web/static/units.js::waitingToTalk`, `knyaz2/web/static/warband.js::warbandSwing` |
| `0x00414af8` | `knyaz2/web/static/actor.js::actorReach`, `knyaz2/web/static/combat.js::reachOf`, `knyaz2/web/static/units.js::canStrike` |
| `0x00415190` | `knyaz2/web/static/dialog.js::dialogRole`, `knyaz2/web/static/village.js::officialRole` |
| `0x00415b20` | `knyaz2/web/static/units.js::enemyOf`, `knyaz2/web/static/warband.js::warbandTick` |
| `0x0041615a` | `knyaz2/web/static/hero.js::unitMove`, `knyaz2/web/static/hero.js::unitTryStep` |
| `0x00416574` | `knyaz2/web/static/hero.js::waveStamp`, `knyaz2/web/static/units.js::unitSendTo` |
| `0x00416b50` | `knyaz2/web/static/actor.js::actorAttackPose`, `knyaz2/web/static/hero.js::heroPlayAction` |
| `0x0041a52c` | `knyaz2/web/static/combat.js::mightTerm`, `knyaz2/web/static/combat.js::shotSnapshot` |
| `0x0041abbc` | `knyaz2/web/static/jewels.js::enchantPrice`, `knyaz2/web/static/trade.js::itemValue` |
| `0x0041b218` | `knyaz2/web/static/carry.js::carriedWeight`, `knyaz2/web/static/carry.js::itemWeight` |
| `0x0041b4cc` | `knyaz2/web/static/combat.js::offHandAccuracy`, `knyaz2/web/static/progress.js::victimSkills` |
| `0x0041c194` | `knyaz2/web/static/combat.js::wearDefence`, `knyaz2/web/static/combat.js::wearSlot` |
| `0x0041c494` | `knyaz2/web/static/dialog.js::healthMax`, `knyaz2/web/static/inventory.js::enchantFromBag`, `knyaz2/web/static/units.js::healthMax` |
| `0x0041c944` | `knyaz2/web/static/clock.js::clockPhaseHits`, `knyaz2/web/static/effects.js::effectsTick`, `knyaz2/web/static/effects.js::healthSet`, `knyaz2/web/static/effects.js::workersOf`, `knyaz2/web/static/worldmap.js::wanderingTick` |
| `0x0041d954` | `knyaz2/web/static/effects.js::potionDrink`, `knyaz2/web/static/effects.js::potionOil`, `knyaz2/web/static/effects.js::potionSmear` |
| `0x0041e280` | `knyaz2/web/static/carry.js::ammoFits`, `knyaz2/web/static/sfx.js::sfxEquip` |
| `0x00421690` | `knyaz2/web/static/carry.js::carryDrop`, `knyaz2/web/static/carry.js::carryOntoStack`, `knyaz2/web/static/carry.js::carryPlaceBag`, `knyaz2/web/static/combat.js::orderAt`, `knyaz2/web/static/progress.js::raiseCharacteristic`, `knyaz2/web/static/sfx.js::sfxClick`, `knyaz2/web/static/sfx.js::sfxSelect`, `knyaz2/web/static/ui.js::partySpeed`, `knyaz2/web/static/warband.js::warbandPlayerAttacks`, `knyaz2/web/static/worldmap.js::startTravelTo` |
| `0x00422afc` | `knyaz2/web/static/inventory.js::pickUp`, `knyaz2/web/static/ui.js::panelToHero` |
| `0x00424514` | `knyaz2/web/static/loot.js::lootSlotOf`, `knyaz2/web/static/shadows.js::renderInsideShadows` |
| `0x00425db4` | `knyaz2/web/static/actor.js::actorLayers`, `knyaz2/web/static/hero.js::drawSelectionCircle`, `knyaz2/web/static/hero.js::heroBodyFrame`, `knyaz2/web/static/units.js::selectionCircle` |
| `0x00425e81` | `knyaz2/web/static/hero.js::drawHeroAtDepth`, `knyaz2/web/static/units.js::renderUnitsOverlay` |
| `0x004277f4` | `knyaz2/web/static/app.js::arrivalText`, `knyaz2/web/static/app.js::heroPathfinder`, `knyaz2/web/static/app.js::meetEnemy`, `knyaz2/web/static/app.js::worldTick`, `knyaz2/web/static/ui.js::markerAt`, `knyaz2/web/static/warband.js::warbandJoin`, `knyaz2/web/static/worldmap.js::markerVisible` |
| `0x00428b88` | `knyaz2/web/static/cursors.js::cursorAt`, `knyaz2/web/static/cursors.js::drawnWeapon` |
| `0x004291b4` | `knyaz2/web/static/hero.js::centreOn`, `knyaz2/web/static/hero.js::centreOnHero` |
| `0x004292dc` | `knyaz2/web/static/carry.js::carryActor`, `knyaz2/web/static/inventory.js::inventorySetup`, `knyaz2/web/static/orders.js::selectionLead`, `knyaz2/web/static/ui.js::panelUnit`, `knyaz2/web/static/ui.js::weaponFace` |
| `0x00429b2c` | `knyaz2/web/static/sfx.js::sfxHumanPose`, `knyaz2/web/static/sfx.js::sfxHurtCry`, `knyaz2/web/static/sfx.js::sfxPose`, `knyaz2/web/static/sfx.js::sfxSwing` |
| `0x0042a8f4` | `knyaz2/web/static/dialog.js::dialogJournal`, `knyaz2/web/static/ui.js::strikeDisplay`, `knyaz2/web/static/ui.js::toggleJournal` |
| `0x0042f22c` | `knyaz2/web/static/carry.js::carryUse`, `knyaz2/web/static/carry.js::unitCanRun` |
| `0x0043096c` | `knyaz2/web/static/ui.js::belt`, `knyaz2/web/static/ui.js::beltArrows`, `knyaz2/web/static/ui.js::beltScale` |
| `0x00433070` | `knyaz2/web/static/units.js::namedFrom`, `knyaz2/web/static/units.js::partyHire` |
| `0x0043346c` | `knyaz2/web/static/trade.js::tradeOpen`, `knyaz2/web/static/trade.js::trader` |
| `0x00436478` | `knyaz2/web/static/dialog.js::resolve`, `knyaz2/web/static/dialog.js::show`, `knyaz2/web/static/dialog.js::speak` |
| `0x00436c48` | `knyaz2/web/static/carry.js::whereIs`, `knyaz2/web/static/craft.js::craftStone`, `knyaz2/web/static/effects.js::drinkWine`, `knyaz2/web/static/questitems.js::powderRules` |
| `0x004387cc` | `knyaz2/web/static/creation.js::loadArchetype`, `knyaz2/web/static/progress.js::creationReset` |
| `0x00438a00` | `knyaz2/web/static/daylight.js::clockTick`, `knyaz2/web/static/progress.js::canLowerCharacteristic`, `knyaz2/web/static/ui.js::uiEscape` |
| `0x0043b670` | `knyaz2/web/static/combat.js::distanceCells`, `knyaz2/web/static/hero.js::cellDistanceCanon`, `knyaz2/web/static/units.js::adjacentCell`, `knyaz2/web/static/units.js::cellRange`, `knyaz2/web/static/warband.js::cellRange` |
| `0x0043b974` | `knyaz2/web/static/hero.js::heroAnchor`, `knyaz2/web/static/sound.js::positional` |
| `0x0043c2e8` | `knyaz2/web/static/hero.js::heroEquipmentAssets`, `knyaz2/web/static/viewport.js::drawSprite` |
| `0x0043df48` | `knyaz2/web/static/buildings.js::buildingsSetup`, `knyaz2/web/static/sound.js::soundMapEnter`, `knyaz2/web/static/viewport.js::zoomFit` |

## Функции без единого адреса, по размеру

Связка и разметка тут нормальны; смотреть надо на те, что считают правила.

| файл и функция | строк |
|---|---|
| `konung2/heroes.py::_crop` | 122 |
| `knyaz2/web/static/hero.js::wavePlan` | 118 |
| `knyaz2/web/static/ambient.js::ambientTick` | 100 |
| `knyaz2/web/static/save.js::applySave` | 93 |
| `knyaz2/web/static/ui.js::renderTrade` | 77 |
| `knyaz2/web/static/save.js::packActor` | 71 |
| `knyaz2/web/static/save.js::applyActor` | 65 |
| `knyaz2/web/static/menu.js::renderSlots` | 59 |
| `knyaz2/web/static/ambient.js::renderAmbient` | 56 |
| `knyaz2/web/static/world.js::loadMap` | 54 |
| `konung2/voices.py::greeting_index` | 50 |
| `knyaz2/web/static/shops.js::restockGoods` | 49 |
| `konung2/res.py::decode_rle` | 45 |
| `knyaz2/web/static/units.js::actorInstanceMaps` | 42 |
| `knyaz2/web/static/menu.js::setMusic` | 40 |
| `knyaz2/web/static/sound.js::soundBindCell` | 40 |
| `knyaz2/web/static/debug.js::renderGroundDebug` | 39 |
| `knyaz2/web/static/sound_lab.js::main` | 39 |
| `knyaz2/web/static/presence.js::presenceTick` | 38 |
| `konung2/pics.py::decode` | 38 |
| `knyaz2/web/static/questitems.js::usePowder` | 37 |
| `konung2/res.py::verify_sprite` | 37 |
| `knyaz2/web/static/actor.js::actorSheetPaths` | 34 |
| `knyaz2/web/static/world.js::mapBounds` | 34 |
| `konung2/trade.py::screen` | 34 |
| `knyaz2/web/static/presence.js::connect` | 32 |
| `knyaz2/web/static/village.js::villageSetup` | 32 |
| `knyaz2/web/static/app.js::pump` | 31 |
| `konung2/cursors.py::decode` | 31 |
| `konung2/res.py::newhero_sprite` | 31 |
| `knyaz2/web/static/craft.js::mixingApply` | 30 |
| `knyaz2/web/static/sound_lab.js::play` | 30 |
| `konung2/world/model.py::_read_grid` | 30 |
| `konung2/gamefile.py::class_kinds` | 29 |
| `knyaz2/web/static/gamemenu.js::gameMenuShow` | 28 |
| `knyaz2/web/static/ui.js::renderTalk` | 28 |
| `knyaz2/web/static/presence.js::apply` | 27 |
| `knyaz2/web/static/content.js::preload` | 26 |
| `knyaz2/web/static/water.js::waterInit` | 26 |
| `knyaz2/web/static/input.js::pinchStart` | 25 |
