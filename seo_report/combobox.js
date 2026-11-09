// Combobox có nhãn, theo mẫu ARIA 1.2 "combobox + listbox":
// - ô nhập role="combobox"; focus luôn ở ô nhập, mục đang chọn báo qua aria-activedescendant
// - danh sách role="listbox" chỉ có trong DOM khi mở; aria-expanded và aria-controls cùng đổi theo trạng thái mở
// - mỗi kết quả role="option" (aria-selected cho giá trị hiện tại)
// - phím: ↓ / ↑ (mở + di chuyển), Home / End, Enter (chọn), Escape (đóng, rồi xóa chữ đang gõ), Tab (đóng)
// - không tự focus khi dựng trang
let uid = 0;

const fold = (s) =>
  String(s ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase()
    .trim();

export default {
  template: `
    <div class="sr-cb">
      <label :id="labelId" :for="inputId" class="sr-cb-label">{{ label }}</label>
      <div class="sr-cb-field" :class="{ open: open }">
        <input
          ref="input"
          :id="inputId"
          type="text"
          role="combobox"
          :aria-labelledby="labelId"
          autocomplete="off"
          spellcheck="false"
          aria-autocomplete="list"
          :aria-expanded="open ? 'true' : 'false'"
          :aria-controls="open ? listId : null"
          :aria-activedescendant="open && active >= 0 ? optionId(active) : null"
          :aria-describedby="hint ? hintId : null"
          :placeholder="placeholder"
          v-model="query"
          @input="onInput"
          @keydown="onKey"
          @click="openList(false)"
          @blur="onBlur"
        />
        <button type="button" class="sr-cb-toggle" tabindex="-1" :aria-label="open ? 'Đóng danh sách' : 'Mở danh sách'"
                @mousedown.prevent @click="toggle">
          <span aria-hidden="true">▾</span>
        </button>
      </div>
      <div v-if="hint" :id="hintId" class="sr-cb-hint">{{ hint }}</div>
      <ul v-if="open" :id="listId" ref="list" role="listbox" :aria-labelledby="labelId" class="sr-cb-list">
        <li v-for="(o, i) in shown" :key="o.value" :id="optionId(i)" role="option"
            :aria-selected="o.value === current ? 'true' : 'false'"
            :class="{ active: i === active, selected: o.value === current }"
            @mousedown.prevent="choose(o)" @mousemove="active = i">{{ o.label }}</li>
      </ul>
      <div v-if="open && !shown.length" class="sr-cb-empty">Không có kết quả</div>
      <div class="sr-only" aria-live="polite" aria-atomic="true">{{ status }}</div>
    </div>`,
  props: {
    value: { default: null },
    options: { type: Array, default: () => [] },
    label: { type: String, default: "" },
    placeholder: { type: String, default: "" },
    hint: { type: String, default: "" },
    limit: { type: Number, default: 60 },
  },
  data() {
    const n = ++uid;
    return {
      inputId: `sr-cb-${n}-input`,
      labelId: `sr-cb-${n}-label`,
      listId: `sr-cb-${n}-list`,
      hintId: `sr-cb-${n}-hint`,
      open: false,
      active: -1,
      query: "",
      typed: false, // đang gõ để lọc (khác với chữ hiện của giá trị đã chọn)
      current: this.value, // giá trị đang chọn phía trình duyệt (máy chủ không gửi lại, LOOPBACK = False)
      status: "",
    };
  },
  computed: {
    selected() {
      return this.options.find((o) => o.value === this.current) || null;
    },
    matches() {
      if (!this.typed || !this.query.trim()) return this.options;
      const q = fold(this.query);
      return this.options.filter((o) => fold(o.label).includes(q));
    },
    shown() {
      return this.matches.slice(0, this.limit);
    },
  },
  watch: {
    value(v) {
      this.current = v; // máy chủ đặt giá trị mới (set_value)
      if (!this.typed) this.query = this.selected ? this.selected.label : "";
    },
    options() {
      if (!this.typed) this.query = this.selected ? this.selected.label : "";
    },
  },
  mounted() {
    this.query = this.selected ? this.selected.label : ""; // không focus khi dựng trang
  },
  methods: {
    optionId(i) {
      return `${this.listId}-opt-${i}`;
    },
    announce() {
      const n = this.matches.length;
      this.status = !n ? "Không có kết quả" : n > this.shown.length
        ? `${n} kết quả, hiện ${this.shown.length} đầu tiên` : `${n} kết quả`;
    },
    openList(fromKey) {
      if (this.open) return;
      this.open = true;
      const i = this.shown.findIndex((o) => o.value === this.current);
      this.active = i >= 0 ? i : fromKey ? 0 : -1;
      this.announce();
      this.$nextTick(this.scrollActive);
    },
    close(revert) {
      this.open = false;
      this.active = -1;
      if (revert) {
        this.typed = false;
        this.query = this.selected ? this.selected.label : "";
      }
    },
    toggle() {
      if (this.open) this.close(true);
      else {
        this.openList(true);
      }
      this.$refs.input.focus(); // bấm nút ▾: đưa focus về ô nhập (focus không bao giờ rời ô nhập khi dùng phím)
    },
    onInput() {
      this.typed = true;
      if (!this.open) this.open = true;
      this.active = this.shown.length ? 0 : -1;
      this.announce();
      this.$nextTick(this.scrollActive);
    },
    move(to) {
      const n = this.shown.length;
      if (!n) return;
      this.active = (to + n) % n;
      this.$nextTick(this.scrollActive);
    },
    scrollActive() {
      const list = this.$refs.list;
      if (!list || this.active < 0) return;
      const el = list.querySelector(`#${CSS.escape(this.optionId(this.active))}`);
      if (el) el.scrollIntoView({ block: "nearest" });
    },
    choose(o) {
      this.typed = false;
      this.query = o.label;
      this.close(false);
      if (o.value !== this.current) {
        this.current = o.value;
        this.$emit("update:value", o.value);
      }
      this.status = `Đã chọn ${o.label}`;
    },
    onKey(e) {
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          if (!this.open) this.openList(true);
          else this.move(this.active + 1);
          break;
        case "ArrowUp":
          e.preventDefault();
          if (!this.open) {
            this.openList(true);
            this.move(this.shown.length - 1);
          } else this.move(this.active - 1);
          break;
        case "Home":
          if (this.open) { e.preventDefault(); this.move(0); }
          break;
        case "End":
          if (this.open) { e.preventDefault(); this.move(this.shown.length - 1); }
          break;
        case "Enter":
          if (this.open && this.active >= 0 && this.shown[this.active]) {
            e.preventDefault();
            this.choose(this.shown[this.active]);
          }
          break;
        case "Escape":
          if (this.open) {
            e.preventDefault();
            e.stopPropagation(); // không đóng luôn hộp thoại chứa ô này
            this.close(true);
          } else if (this.typed) {
            e.preventDefault();
            this.close(true);
          }
          break;
        case "Tab":
          if (this.open) this.close(true);
          break;
      }
    },
    onBlur() {
      if (this.open) this.close(true);
      else if (this.typed) this.close(true);
    },
  },
};
