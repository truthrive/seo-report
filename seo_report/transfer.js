// Transfer hai khung (tương đương Ant Design Transfer): khung trái "Có thể chọn", khung phải "Đã chọn".
// targetKeys = các khóa đang ở khung phải. Mỗi khung có tiêu đề, ô tìm, ô "chọn tất cả", danh sách role="listbox"
// aria-multiselectable="true" với các dòng role="option" (aria-selected = đã đánh dấu để chuyển).
// Focus bàn phím (aria-activedescendant) tách khỏi việc đánh dấu: ↑ ↓ Home End di chuyển, Space / Enter đánh dấu.
// Nút chuyển chỉ bật khi có mục hợp lệ đã đánh dấu (và khung phải còn chỗ nếu có giới hạn `max`).
// Không tự chuyển: phát sự kiện "change" {targetKeys, direction, moveKeys}; máy chủ áp dụng rồi gửi targetKeys mới.
let uid = 0;
const fold = (s) =>
  String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D")
    .toLowerCase().trim();

const pane = {
  props: ["side", "title", "items", "checked", "emptyText", "uid", "unit"],
  emits: ["toggle", "set"],
  data() { return { query: "", active: -1 }; },
  computed: {
    titleId() { return `sr-tf-${this.uid}-${this.side}-title`; },
    listId() { return `sr-tf-${this.uid}-${this.side}-list`; },
    shown() {
      const q = fold(this.query);
      return q ? this.items.filter((o) => fold(o.title + " " + (o.description || "")).includes(q)) : this.items;
    },
    eligible() { return this.shown.filter((o) => !o.disabled); },
    nChecked() { return this.items.filter((o) => this.checked.includes(o.key)).length; },
    allState() {
      const n = this.eligible.filter((o) => this.checked.includes(o.key)).length;
      return n === 0 ? "none" : n === this.eligible.length ? "all" : "some";
    },
  },
  template: `
    <section class="sr-tf-pane" role="group" :aria-labelledby="titleId">
      <header class="sr-tf-head">
        <input type="checkbox" class="sr-tf-all" :checked="allState === 'all'"
               :indeterminate.prop="allState === 'some'" :disabled="!eligible.length"
               :aria-label="'Đánh dấu tất cả trong ' + title" @change="$emit('set', eligible.map(o => o.key), $event.target.checked)" />
        <h3 :id="titleId" class="sr-tf-title">{{ title }}</h3>
        <span class="sr-tf-count">{{ nChecked ? nChecked + '/' : '' }}{{ items.length }} {{ unit }}</span>
      </header>
      <input type="text" class="sr-tf-search" v-model="query" autocomplete="off" spellcheck="false"
             :aria-label="'Tìm trong ' + title" :aria-controls="listId" placeholder="Gõ để tìm"
             @keydown.down.prevent="focusList" />
      <ul :id="listId" ref="list" role="listbox" aria-multiselectable="true" :aria-labelledby="titleId"
          :tabindex="shown.length ? 0 : -1"
          :aria-activedescendant="active >= 0 && shown[active] ? optId(active) : null"
          @focus="onFocus" @keydown="onKey">
        <li v-for="(o, i) in shown" :key="o.key" :id="optId(i)" role="option"
            :aria-selected="checked.includes(o.key) ? 'true' : 'false'" :aria-disabled="o.disabled ? 'true' : null"
            :class="{ active: i === active, sel: checked.includes(o.key), off: o.disabled }"
            @mousedown.prevent @click="pick(i)">
          <span class="sr-ms-box" aria-hidden="true"><q-icon v-if="checked.includes(o.key)" name="check" size="14px" /></span>
          <span class="sr-tf-text"><span class="sr-tf-name">{{ o.title }}</span>
            <span v-if="o.description" class="sr-tf-desc">{{ o.description }}</span></span>
        </li>
      </ul>
      <div v-if="!shown.length" class="sr-tf-empty">{{ query ? 'Không có kết quả' : emptyText }}</div>
    </section>`,
  methods: {
    optId(i) { return `${this.listId}-opt-${i}`; },
    onFocus() { if (this.active < 0 && this.shown.length) this.active = 0; },
    pick(i) {
      this.active = i;
      const o = this.shown[i];
      if (o && !o.disabled) this.$emit("toggle", o.key);
    },
    focusList() { if (this.shown.length) { this.$refs.list.focus(); if (this.active < 0) this.active = 0; } },
    move(to) {
      const n = this.shown.length;
      if (!n) return;
      this.active = Math.max(0, Math.min(n - 1, to));
      this.$nextTick(() => { const el = document.getElementById(this.optId(this.active)); if (el) el.scrollIntoView({ block: "nearest" }); });
    },
    onKey(e) {
      const k = e.key;
      if (k === "ArrowDown") { e.preventDefault(); this.move(this.active + 1); }
      else if (k === "ArrowUp") { e.preventDefault(); this.move(this.active - 1); }
      else if (k === "Home") { e.preventDefault(); this.move(0); }
      else if (k === "End") { e.preventDefault(); this.move(this.shown.length - 1); }
      else if (k === " " || k === "Enter") {
        e.preventDefault();
        const o = this.shown[this.active];
        if (o && !o.disabled) this.$emit("toggle", o.key);
      } else if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "a") {
        e.preventDefault();
        this.$emit("set", this.eligible.map((o) => o.key), this.allState !== "all");
      }
    },
  },
};

export default {
  components: { "sr-tf-pane": pane },
  template: `
    <div class="sr-tf">
      <sr-tf-pane side="left" :uid="uid" :title="titles[0]" :items="leftItems" :checked="leftChecked"
                  :empty-text="emptyText[0]" :unit="unit" @toggle="k => flip('left', k)" @set="(ks, on) => setMany('left', ks, on)" />
      <div class="sr-tf-ops" role="group" aria-label="Chuyển mục giữa hai khung">
        <button type="button" class="sr-tf-btn" :disabled="!canRight" @click="move('right')"
                :aria-label="'Chuyển ' + leftChecked.length + ' mục sang ' + titles[1]">
          <span>{{ operations[0] }}</span><q-icon name="chevron_right" size="18px" aria-hidden="true" />
        </button>
        <button type="button" class="sr-tf-btn" :disabled="!canLeft" @click="move('left')"
                :aria-label="'Chuyển ' + rightChecked.length + ' mục về ' + titles[0]">
          <q-icon name="chevron_left" size="18px" aria-hidden="true" /><span>{{ operations[1] }}</span>
        </button>
        <div v-if="overLimit" class="sr-tf-limit">Chỉ còn {{ room }} chỗ (tối đa {{ max }})</div>
      </div>
      <sr-tf-pane side="right" :uid="uid" :title="titles[1]" :items="rightItems" :checked="rightChecked"
                  :empty-text="emptyText[1]" :unit="unit" @toggle="k => flip('right', k)" @set="(ks, on) => setMany('right', ks, on)" />
      <div class="sr-only" aria-live="polite" aria-atomic="true">{{ status }}</div>
    </div>`,
  props: {
    data: { type: Array, default: () => [] },           // [{key, title, description?, disabled?}]
    targetKeys: { type: Array, default: () => [] },     // khóa đang ở khung phải
    titles: { type: Array, default: () => ["Có thể chọn", "Đã chọn"] },
    operations: { type: Array, default: () => ["Thêm", "Bỏ"] },
    emptyText: { type: Array, default: () => ["Không còn mục nào", "Chưa chọn mục nào"] },
    unit: { type: String, default: "mục" },
    max: { type: Number, default: 0 },                  // 0 = không giới hạn số mục ở khung phải
  },
  data() { return { uid: ++uid, leftChecked: [], rightChecked: [], status: "" }; },
  computed: {
    leftItems() { return this.data.filter((o) => !this.targetKeys.includes(o.key)); },
    rightItems() { return this.data.filter((o) => this.targetKeys.includes(o.key)); },
    room() { return this.max ? Math.max(0, this.max - this.targetKeys.length) : Infinity; },
    overLimit() { return this.max && this.leftChecked.length > this.room; },
    canRight() { return this.leftChecked.length > 0 && !this.overLimit; },
    canLeft() { return this.rightChecked.length > 0; },
  },
  watch: {
    targetKeys() {  // máy chủ đã áp dụng: bỏ đánh dấu các mục không còn ở khung đó
      const left = this.leftItems.map((o) => o.key), right = this.rightItems.map((o) => o.key);
      this.leftChecked = this.leftChecked.filter((k) => left.includes(k));
      this.rightChecked = this.rightChecked.filter((k) => right.includes(k));
    },
  },
  methods: {
    flip(side, key) {
      const arr = side === "left" ? "leftChecked" : "rightChecked";
      this[arr] = this[arr].includes(key) ? this[arr].filter((k) => k !== key) : [...this[arr], key];
    },
    setMany(side, keys, on) {
      const arr = side === "left" ? "leftChecked" : "rightChecked";
      this[arr] = on ? [...new Set([...this[arr], ...keys])] : this[arr].filter((k) => !keys.includes(k));
    },
    move(direction) {
      const moveKeys = direction === "right" ? [...this.leftChecked] : [...this.rightChecked];
      if (!moveKeys.length || (direction === "right" && !this.canRight)) return;
      const next = direction === "right" ? [...this.targetKeys, ...moveKeys]
        : this.targetKeys.filter((k) => !moveKeys.includes(k));
      this.status = `Đang chuyển ${moveKeys.length} mục ${direction === "right" ? "sang " + this.titles[1] : "về " + this.titles[0]}`;
      this.$emit("change", { targetKeys: next, direction, moveKeys });
    },
  },
};
