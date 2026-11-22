# Notes: Batch Normalization: Accelerating Deep Network Training by Reducing Internal Covariate Shift

case_id: `1502.03167` · source: `paper.pdf` (sha256 bdc69e0b568f…) · status: **success** · built 2026-11-22T09:44:32Z by paper-notes 1.0.0

Citation format: 〔p.PAGE §SECTION BLOCK〕; BLOCK = p{page}-b{n} in `parsed/*/doc.json`. ⚠ = needs human review, ✗ = check failed.

## 1. Paper card

**title** — Paper title as printed
- Batch Normalization: Accelerating Deep Network Training by Reducing Internal Covariate Shift 〔p.1 p1-b1; p.1 p1-b2〕

**authors** — Authors (and affiliations if useful)
- Sergey Ioffe Google Inc., sioffe@google.com 〔p.1 p1-b3〕

**venue_year** — Venue / year / arXiv id if printed in the PDF
- *not reported:* venue not printed in the text layer

**research_question** — The question or problem the paper sets out to answer
- 能否通过在网络结构中对各层输入做归一化来减少内部协变量偏移（ICS），从而加速深层网络训练？ 〔p.2 §1 p2-b5〕

**motivation_gap** — Why it matters / what gap in prior work it addresses
- 各层输入分布随前层参数变化，需要更小学习率和谨慎初始化，饱和非线性难以训练 〔p.1 Abstract p1-b5〕

**contributions** — What the authors claim as their contributions
- *not reported:* no explicit contribution list

**data** — Data, datasets, samples, corpora, benchmarks, materials (with sizes/splits as printed)
- MNIST：28x28 二值图像输入，3 个各 100 单元的全连接隐层，训练 50000 步、每 mini-batch 60 个样本 〔p.5 §4.1 p5-b26; p.6 §4.1 p6-b3〕
- ImageNet（LSVRC2012）分类，1000 类；Figure 4 的对比基于 50000 张验证集图像 〔p.7 §4.2.2 p7-b3; p.6 §4.2 p6-b7; p.8 §5 Figure 4〕

**method** — Approach / model / experimental or analytical design
- 逐维归一化（均值 0、方差 1），并引入可学习的缩放 γ 和平移 β 以保持表示能力 〔p.3 §3 p3-b10; p.3 §3 p3-b14〕
- 用 mini-batch 统计量估计均值方差（Algorithm 1），推理时改用总体统计量 〔p.3 §3 p3-b18; p.4 §3.1 p4-b48〕

**conditions** — Assumptions, settings, hyper-parameters, scope conditions the conclusions depend on
- 训练需 mini-batch 大小 m > 1 〔p.4 §3.1 p4-b45〕
- BN 加在非线性之前，归一化 x = Wu+b；卷积层按特征图跨位置联合归一化 〔p.5 §3.2 p5-b3; p.5 §3.2 p5-b7〕
- ImageNet 实验：Inception 变体，mini-batch 32，Inception 初始学习率 0.0015，BN-x5 为 0.0075，BN-x30 为 0.045 〔p.6 §4.2 p6-b8; p.7 §4.2.2 p7-b4; p.7 §4.2.2 p7-b6; p.7 §4.2.2 p7-b7〕

**main_findings** — Main results, with numbers as printed
- BN-x5 只需 Inception 1/14 的步数即达到 72.2% 精度 〔p.7 §4.2.2 p7-b12〕
- BN-x30 最高验证精度 74.8%，到达 72.2% 所需步数为 2.7·10^6（Inception 为 31.0·10^6） 〔p.7 §4.2.2 p7-b15; p.7 §4.2.2 p7-b15〕
- 集成模型 top-5 验证误差 4.9%、测试误差 4.82%，优于此前最佳 4.94% 〔p.7 §4.2.3 p7-b19; p.7 §4.2.3 p7-b19〕
- BN-x5-Sigmoid 达到 69.8%，而无 BN 的 sigmoid Inception 不超过 1/1000 精度 〔p.7 §4.2.2 p7-b17〕

**conclusion** — What the authors conclude
- BN 通过把归一化纳入网络结构加速训练，可用更高学习率、去掉 Dropout，并在 ImageNet 上超越当时最佳结果 〔p.8 §5 p8-b4〕

**limitations** — Limitations stated by the authors (or 'not reported' + reason)
- 作者承认尚未探索 BN 的全部可能；BN 使 Jacobian 奇异值接近 1 仅为猜想 〔p.8 §5 p8-b7; p.5 §3.3 p5-b21〕

**future_work** — Open problems / future work stated
- 应用于 RNN、检验能否帮助领域自适应 〔p.8 §5 p8-b7〕

## 2. Section-by-section notes (paper's own order)

### Abstract  (pp. 1–1, `s1`)
- *purpose*:
  - 提出 BN 以缓解内部协变量偏移、加速训练 〔p.1 Abstract p1-b5〕

### 1 Introduction  (pp. 1–2, `s2`)
- *purpose*:
  - 从 SGD 与 mini-batch 出发，引出层输入分布变化问题并定义 ICS 〔p.2 §1 p2-b5〕
- *transition*:
  - 预告第 4.2 节用 7% 的训练步数匹配 Inception 〔p.2 §1 p2-b6〕

### 2 Towards Reducing Internal Covariate Shift  (pp. 2–3, `sx1`)
- *method*:
  - 讨论白化：若优化忽略归一化依赖，偏置 b 会无限增长 〔p.2 §2 p2-b10〕
- *conclusion*:
  - 完整白化代价高（需协方差矩阵及其逆平方根），促使下一节简化 〔p.3 §2 p3-b7〕

### 3 Normalization via Mini-Batch Statistics  (pp. 3–4, `sx2`)
- *method*:
  - 两项简化：逐维归一化；用 mini-batch 统计量 〔p.3 §3 p3-b10〕

#### 3.1 Training and Inference with Batch-Normalized Networks  (pp. 4–4, `sx3`)
- *method*:
  - 训练用 mini-batch 统计量，推理用总体统计量，归一化变为确定性线性变换 〔p.4 §3.1 p4-b51〕

#### 3.2 Batch-Normalized Convolutional Networks  (pp. 4–5, `sx4`)
- *method*:
  - 卷积层中同一特征图不同位置按相同方式归一化 〔p.5 §3.2 p5-b7〕

#### 3.3 Batch Normalization enables higher learning rates  (pp. 5–5, `sx5`)
- *results*:
  - 反向传播不受参数尺度影响，可用更高学习率 〔p.5 §3.3 p5-b11〕

#### 3.4 Batch Normalization regularizes the model  (pp. 5–5, `sx6`)
- *conclusion*:
  - BN 有正则化效果，可减少或去掉 Dropout 〔p.5 §3.4 p5-b23〕

### 4 Experiments  (pp. 5–5, `s5`)
- *(no notes for this section)*

#### 4.1 Activations over time  (pp. 5–6, `s6`)
- *results*:
  - MNIST 上 BN 网络测试精度更高，sigmoid 输入分布更稳定 〔p.6 §4.1 p6-b4〕

#### 4.2 ImageNet classification  (pp. 6–6, `s7`)
- *method*:
  - 在 Inception 变体上加 BN，mini-batch 32 〔p.6 §4.2 p6-b8〕

#### 4.2.1 Accelerating BN Networks  (pp. 6–7, `s8`)
- *method*:
  - 配套修改：提高学习率、去 Dropout、L2 权重降为 1/5、学习率衰减快 6 倍、去 LRN、更彻底打乱、减少光度扰动 〔p.6 §4.2.1 p6-b14; p.6 §4.2.1 p6-b15〕

#### 4.2.2 Single-Network Classification  (pp. 7–7, `s9`)
- *results*:
  - BN-Baseline 不到一半步数即匹配 Inception 〔p.7 §4.2.2 p7-b12〕

#### 4.2.3 Ensemble Classification  (pp. 7–7, `s10`)
- *results*:
  - 6 个基于 BN-x30 的网络集成，测试 top-5 误差 4.82% 〔p.7 §4.2.3 p7-b20; p.7 §4.2.3 p7-b19〕

### 5 Conclusion  (pp. 7–8, `s11`)
- *conclusion*:
  - 总结：BN 在架构内归一化，可配合任意优化方法；并说明与 standardization layer 的区别 〔p.8 §5 p8-b3〕

### Appendix  (pp. 9–11, `s13`)
- *(no notes for this section)* — appendix: Inception variant details, not summarised

## 3. Knowledge points

| term | aliases | kind | definition / statement | where |
|---|---|---|---|---|
| Internal Covariate Shift | ICS, 内部协变量偏移 (abbr. check: expansion_not_printed) | concept | 训练中由于网络参数变化导致网络激活分布的变化 | 〔p.2 §2 p2-b8〕 ⚠ |
| BN | Batch Normalization, 批归一化 (abbr. check: found_in_text) | method | 用 mini-batch 统计量对激活归一化并缩放平移 | 〔p.3 §3 p3-b23; p.3 §3 p3-b44〕 |
| γ, β | scale and shift parameters | variable | 每个激活的可学习缩放与平移参数 | 〔p.3 §3 p3-b14〕 |

## 4. Not reported / uncertain / conflicts
- unreported `card.contributions`: no explicit contribution list
- unreported `card.venue_year`: venue not printed in the text layer

## 5. Verification summary
- items: 37 · verified 37 · needs review 0 · failed 0
- section coverage: 7/7 top-level sections; missing: none
- card fields missing without reason: none
- machine-checked: anchor exists, quote verbatim in the cited block, page/section of the anchor, numbers in note ⊂ anchored text, abbreviation expansions. Human check needed: whether the note's wording is a faithful reading of the quote, figure readings, page-image readings, fuzzy quotes.
