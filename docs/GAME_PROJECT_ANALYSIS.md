# H:\zhangjunjie_stage_1 游戏项目分析报告

基于目录结构、Unity 配置、C# 业务代码与配置表枚举的静态分析，推断该项目所对应的游戏类型与内容。

---

## 详细总结（可作配置/简报用）

**项目**：心动（xd）发行的 **FantasyWorld（幻想世界）** 项目 **stage** 版本客户端，内部产品代号 xdt；P4 流为 `//FantasyWorld/stage/Client`，Unity 产品名为 xdt，支持 PC（含 Themis 插件）、Android、iOS。

**游戏类型**：**模拟经营 + 家园养成 + 社交 + 多小游戏** 的 **休闲生活类游戏**，整体可概括为「种田 + 建造 + 动物 + 钓鱼 + 烹饪 + 活动派对 + 图鉴收集」的综合体。

**核心玩法模块**：
- **家园/农场**：种植（作物/植物/杂草/南瓜）、建造、浇水施肥、生长阶段、收获；配置表含 Crop/Cropplant/Cropseed/Cropfertilizer 等。
- **动物**：饲养、互动、旅行、好感树、栖息地、喂食；AnimalUnit/AnimalInteract/AnimalTravel/AnimalFavorabilityTree 等。
- **制作/烹饪**：配方、食材、烹饪、染色；CookingRecipe、Recipe、Dye 相关 UI。
- **钓鱼**：钓鱼、船、鱼影、水族箱收集；Fish/Fishboat/Fishtankcollection。
- **商店/经济**：百货、活动商店、建造商店、外观商店、战令商店、红点与商城功能开关。
- **扭蛋/抽卡**：Gashapon 演出、卡池、碎片与直购。
- **图鉴**：Pictorial 图鉴分类与收集进度，与战令等联动。
- **研究**：研究机、升级与产出。
- **剧情/任务**：Task 驱动 + Timeline 演出（NormalTimeline/GashaponTimeline），场景有 Main、Craft、MicroHome；配置 logic/timeline.xlsx 等。
- **活动/派对**：捉迷藏、萤火虫派对、音乐派对、鱼潮、观鸟、泡泡派对、小黄鸭跳跃、捉虫、建造比赛等，配套活动任务与奖励。
- **其他**：雪雕、双人/协作秋千、过山车、战令（BattlePass）、社区、邮件、书籍/绘图/明信片/电影屏、录音等。

**技术要点**：Unity + C#，ECS 架构（EcsClient/EcsSystem），配置来自 Excel（logic/*.xlsx、entity 等），音频 Wwise，插件 Themis（PC）、心动 SDK、TapDB、LeanCloud 等。

**体验定位**：轻松、收集、社交、任务与剧情并重，适合按「种田 + 社交 + 小游戏合集」的休闲生活类产品做功能与测试范围理解。

---

## 一、项目身份

| 项目 | 说明 |
|------|------|
| **公司** | xd（心动） |
| **产品名** | xdt（`ProjectSettings/ProjectSettings.asset` 中 `productName: xdt`） |
| **P4 仓库/流** | `//FantasyWorld/stage/Client` → 项目代号 **FantasyWorld**，分支 **stage** |
| **引擎与平台** | Unity 客户端，含 PC（含 Themis 插件更新）、Android、iOS 等 |

结论：心动发行的 **FantasyWorld（幻想世界）** 项目的 **stage** 版本客户端，内部产品代号 xdt。

---

## 二、游戏类型与核心玩法

从 `XDTLevelAndEntity`、`EcsClient`、配置表（`ExcelTableType`）及 UI 面板可归纳出：

**整体定位**：**模拟经营 + 家园养成 + 社交 + 多小游戏** 的 **休闲生活类游戏**，玩法上接近「种田 + 建造 + 动物 + 钓鱼 + 烹饪 + 活动派对 + 图鉴收集」的综合体。

### 1. 家园 / 农场（Homeland / Farm）

- **种植**：`CropComponent`、`PlantComponent`、`CropWeedComponent`、`PumpkinCultivateComponent`（作物、植物、杂草、南瓜培育）
- **建造**：`BuildComponent`，建造物有 transform 更新、施肥/育种等状态
- **配置表**：`TableCrop`、`TableCropplant`、`TableCropseed`、`TableCropfertilizer`、`TableCropbyproduct`、`TableCroplevel`、`TableCroploot`、`TableCropdecoration` 等
- **逻辑**：浇水、施肥、生长阶段、收获、双季作物、与 Farm 模块（如 `CropInfoComponent`、`BoxSoilComponent`）联动

→ 核心循环包含：**种地、浇水施肥、除杂草、收获、扩建家园**。

### 2. 动物系统（Animal）

- **配置表**：`TableAnimalUnit`、`TableAnimalInteract`、`TableAnimalTravel`、`TableAnimalFavorabilityTree`、`TableAnimalHabitat`、`TableAnimalcommonfood`、`TableAnimalMotion`、`TableAnimalCharacter`、`TableAnimalGroup` 等
- **玩法**：动物单位、互动、旅行、好感树、栖息地、喂食、行为与分组

→ **饲养、互动、培养好感、动物出行** 等典型牧场/动物园式玩法。

### 3. 制作与烹饪（Craft / Cooking）

- **配置表**：`TableCookingRecipe`、`TableRecipe`、`TableIngredients`
- **UI**：`DyeColorPanel`（染色）、Craft 相关面板
- **玩法**：配方、食材、烹饪、染色等 **制造与合成**。

### 4. 钓鱼（Fishing）

- **配置表**：`TableFish`、`TableFishboat`、`TableFishshadow`、`TableFishtankcollection`
- **玩法**：钓鱼、船、鱼影、水族箱收集。

### 5. 商店与经济

- **商店**：`ShopEntryWidget`、`PayToBuyShop`、`DepartmentStore`（百货）、`ActivityShop`、`BuildShopItem`、`FaceShopPanel`、`BattlePassShopPanel` 等
- **系统**：`FeatureOpenEnum.Mall`、红点（如 `RedPointEnum.ShopFreeRewardRoot`）、战令商店等

→ **多种商店形态 + 付费/活动/建造/外观/战令** 的完整商业化与资源循环。

### 6. 扭蛋 / 抽卡（Gashapon）

- **剧情演出**：`GashaponTimeline`、`TriggerGashaponTimeline`
- **UI**：`GachaPoolBase`、`GachaTipWidget`、`GachaDirectBuyPieceRewardItemWidget`
- **玩法**：抽卡演出、卡池、碎片与直购。

### 7. 图鉴与收集（Pictorial）

- **模块**：`PictorialModule_Context`、`PictorialTypeWidget`
- **配置**：`TablePedia` 等
- **玩法**：图鉴分类、收集进度、与 BattlePass 图鉴等联动。

### 8. 研究系统（Research）

- **组件**：`ResearchShopMachineComponent`、`ResearchSystem`
- **玩法**：研究机、升级与商店类研究产出。

### 9. 剧情与任务（Timeline / Task）

- **Timeline**：`TriggerTimelineModule`、`NormalTimeline`、`GashaponTimeline`，支持 NPC、对话、特效、镜头、扭蛋演出
- **触发**：Task 事件（Created/Updated/Removed） + `TableTimelinetrigger` 配置表（triggerType | triggerId | triggerParam）
- **场景**：`GameLevel_Main`、`GameLevel_Craft`、`GameLevel_MicroHome`
- **配置**：`logic/timeline.xlsx[timelineassets]` 等

→ **任务驱动的剧情演出与关卡形态**（主城、制作、小家）。

### 10. 活动与派对（Activities / Parties）

从 ECS 与配置可见大量 **限时活动与派对小游戏**：

| 活动/派对 | 说明 |
|-----------|------|
| HideAndSeek | 捉迷藏（含 GM 触发的阶段、角色转换等） |
| GlowwormParty | 萤火虫派对 |
| MusicParty | 音乐派对 |
| FishTide | 鱼潮 |
| BirdWatching | 观鸟 |
| BubbleParty | 泡泡派对 |
| YellowDuckJumpingParty | 小黄鸭跳跃派对 |
| InsectCatching | 捉虫（含昆虫收集、生态盒等） |
| BuildCompetition | 建造比赛 |
| ActivityEvent / ActivityMission | 活动任务、进度奖励、折扣商店等 |

→ **强活动向**：多种派对与季节/主题活动，配合任务、奖励与商店。

### 11. 其他玩法与系统

- **雪雕**：`SnowSculpture`、`SnowMachineComponent`
- **秋千**：`DoubleSwingComponent`、`CooperativeSwingComponent`（双人/协作）
- **过山车**：`RollerCoasterStatusPanel`
- **BattlePass**：战令、挑战、图鉴、商店、任务等完整战令体系
- **社区与社交**：`CommunityPanel`、`CommunityInfoPanel`、邮件、表情、头泡聊天等
- **内容创作**：`Book`（书籍/绘本）、`Drawing`、`Postcard`、`MovieScreen`、`RecordMusicPanel` 等

---

## 三、技术架构要点

- **客户端**：Unity（C#），ECS 风格（EcsClient / EcsSystem），多场景 Level（Main / Craft / MicroHome）
- **配置**：策划表为 Excel（如 `logic/*.xlsx`、entity 相关表），导出后由代码读取（如 `Table*` 枚举对应表）
- **音频**：Wwise（工程内 `WwisePro` 目录）
- **第三方**：心动 SDK（account、payment、share、ads、mainland 等）、TapDB、LeanCloud 等
- **插件**：Themis（`Assets/Plugins/Themis_Plugins`，Jira 中常与「PC 更新」一起出现）

---

## 四、总结：这是什么游戏？

- **类型**：心动（XD）发行的 **FantasyWorld（幻想世界）** 项目 **stage** 版本客户端（产品代号 xdt）。
- **玩法**：以 **家园/农场种植与建造** 为核心，结合 **动物饲养、钓鱼、烹饪/制作、图鉴收集、扭蛋、研究**，并围绕 **多种活动与派对小游戏**（捉迷藏、萤火虫/音乐/泡泡/小黄鸭派对、鱼潮、观鸟、捉虫、建造比赛等）做长线内容与运营。
- **体验**：轻松、收集、社交、任务与剧情演出并重，适合作为 **「种田 + 社交 + 小游戏合集」** 的休闲生活类产品来理解与测试。

若你希望把这份结论用于 **AI 测试范围**（如 `config.json` 的 `ai.game_description`），可摘取上文的「整体定位」与「核心玩法」段落，或自行压缩为几句项目与玩法描述即可。
