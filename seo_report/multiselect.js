// Multi-select: nút gọn (hiện số đã chọn) mở một danh sách có ô tìm; danh sách là role="listbox"
// aria-multiselectable="true", mỗi dòng role="option" bật / tắt aria-selected mà danh sách vẫn mở.
// Focus bàn phím (mục đang sáng, aria-activedescendant) tách khỏi lựa chọn (aria-selected):
// ↑ ↓ Home End chỉ di chuyển; Space / Enter mới bật / tắt. Giá trị đã chọn hiện thành chip có nút bỏ.
let uid = 0;
const fold = (s) =>
  String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D")
    .toLowerCase().trim();

export default {
  template: `
    <div class="sr-ms" :class="{ inline: inline, 'pop-right': popRight }" ref="root">
      <span :id="labelId" class="sr-ms-label">{{ label }}</span>
      <button ref="trigger" type="button" class="sr-ms-trigger" aria-haspopup="listbox"
              :aria-expanded="open ? 'true' : 'false'" :aria-controls="open ? popId : null"
              :aria-labelledby="labelId + ' ' + countId" @click="toggle" @keydown="onTriggerKey">
        <span :id="countId">{{ summary }}</span>
        <q-icon name="expand_more" size="18px" aria-hidden="true" class="sr-ms-caret" />
      </button>
      <div v-if="open" :id="popId" class="sr-ms-pop">
        <input ref="search" type="text" class="sr-ms-search" v-model="query" autocomplete="off" spellcheck="false"
               :placeholder="placeholder" :aria-label="'Tìm trong ' + label" :aria-controls="listId"
               @input="onInput" @keydown="onSearchKey" />
        <div class="sr-ms-bulk">
          <button type="button" @click="setAll(true)">Chọn tất cả{{ query ? ' kết quả' : '' }}</button>
          <button type="button" @click="setAll(false)">Bỏ chọn{{ query ? ' kết quả' : ' hết' }}</button>
        </div>
        <ul :id="listId" ref="list" role="listbox" aria-multiselectable="true" :aria-labelledby="labelId"
            tabindex="0" :aria-activedescendant="active >= 0 && shown[active] ? optionId(active) : null"
            @keydown="onListKey" @focus="onListFocus">
          <li v-for="(o, i) in shown" :key="o.value" :id="optionId(i)" role="option"
              :aria-selected="isSel(o) ? 'true' : 'false'" :class="{ active: i === active, sel: isSel(o) }"
              @mousedown.prevent @click="clickOpt(i)">
            <span class="sr-ms-box" aria-hidden="true"><q-icon v-if="isSel(o)" name="check" size="14px" /></span>
            <span class="sr-ms-text">{{ o.label }}</span>
          </li>
        </ul>
        <div v-if="!shown.length" class="sr-ms-empty">Không có kết quả</div>
        <div class="sr-ms-foot">
          <span class="sr-ms-hint">↑ ↓ di chuyển · Space chọn / bỏ · Esc đóng</span>
          <button type="button" class="sr-ms-done" @click="close(true)">Xong</button>
        </div>
      </div>
      <div v-if="chips && picked.length && (chipsWhenAll || picked.length < options.length)" class="sr-ms-chips">
        <span v-for="o in picked" :key="o.value" class="sr-chip">
          <span class="sr-chip-text">{{ o.label }}</span>
          <button type="button" class="sr-chip-x" :aria-label="'Bỏ ' + o.label" @click="remove(o)">
            <q-icon name="close" size="14px" aria-hidden="true" />
          </button>
        </span>
      </div>
      <div class="sr-only" aria-live="polite" aria-atomic="true">{{ status }}</div>
    </div>`,
  props: {
    value: { type: Array, default: () => [] },
    options: { type: Array, default: () => [] },
    label: { type: String, default: "" },
    placeholder: { type: String, default: "Gõ để tìm" },
    chips: { type: Boolean, default: true },
    chipsWhenAll: { type: Boolean, default: true },  // false: chọn tất cả thì không hiện chip (đỡ rối)
    inline: { type: Boolean, default: false },       // nhãn nằm cùng hàng với nút
    popRight: { type: Boolean, default: false },     // danh sách canh mép phải nút (nút ở sát lề phải)
  },
  data() {
    const n = ++uid;
    return {
      labelId: `sr-ms-${n}-label`, countId: `sr-ms-${n}-count`, popId: `sr-ms-${n}-pop`, listId: `sr-ms-${n}-list`,
      open: false, query: "", active: -1, current: [...this.value], status: "",
    };
  },
  computed: {
    shown() {
      const q = fold(this.query);
      return q ? this.options.filter((o) => fold(o.label).includes(q)) : this.options;
    },
    picked() {
      return this.options.filter((o) => this.current.includes(o.value));
    },
    summary() {
      const n = this.current.length, all = this.options.length;
      return n === all ? `Tất cả (${all})` : n ? `Đã chọn ${n}/${all}` : "Chưa chọn";
    },
  },
  watch: {
    value(v) { this.current = [...v]; },
  },
  mounted() { document.addEventListener("mousedown", this.onOutside); },
  unmounted() { document.removeEventListener("mousedown", this.onOutside); },
  methods: {
    optionId(i) { return `${this.listId}-opt-${i}`; },
    isSel(o) { return this.current.includes(o.value); },
    clickOpt(i) { this.active = i; this.toggleOpt(this.shown[i]); },
    emit() { this.$emit("update:value", [...this.current]); },
    toggleOpt(o) {
      const on = !this.isSel(o);
      this.current = on ? [...this.current, o.value] : this.current.filter((v) => v !== o.value);
      this.status = `${on ? "Đã chọn" : "Đã bỏ"} ${o.label}. ${this.summary}`;
      this.emit();
    },
    remove(o) {
      this.current = this.current.filter((v) => v !== o.value);
      this.status = `Đã bỏ ${o.label}. ${this.summary}`;
      this.emit();
      this.$nextTick(() => this.$refs.trigger && this.$refs.trigger.focus());
    },
    setAll(on) {
      const keys = this.shown.map((o) => o.value);
      this.current = on ? [...new Set([...this.current, ...keys])] : this.current.filter((v) => !keys.includes(v));
      this.status = this.summary;
      this.emit();
    },
    openPop(focusList) {
      this.open = true;
      this.active = -1;
      this.$nextTick(() => {
        if (focusList) { this.active = this.shown.length ? 0 : -1; this.$refs.list && this.$refs.list.focus(); }
        else this.$refs.search && this.$refs.search.focus();
      });
    },
    close(returnFocus) {
      if (!this.open) return;
      this.open = false;
      this.query = "";
      this.active = -1;
      if (returnFocus) this.$nextTick(() => this.$refs.trigger && this.$refs.trigger.focus());
    },
    toggle() { this.open ? this.close(true) : this.openPop(false); },
    onOutside(e) { if (this.open && this.$refs.root && !this.$refs.root.contains(e.target)) this.close(false); },
    onInput() { this.active = this.shown.length ? 0 : -1; this.status = `${this.shown.length} kết quả`; },
    move(to) {
      const n = this.shown.length;
      if (!n) return;
      this.active = Math.max(0, Math.min(n - 1, to));
      this.$nextTick(() => {
        const el = document.getElementById(this.optionId(this.active));
        if (el) el.scrollIntoView({ block: "nearest" });
      });
    },
    onTriggerKey(e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); this.openPop(true); }
      else if (e.key === "Escape" && this.open) { e.preventDefault(); e.stopPropagation(); this.close(true); }
    },
    onSearchKey(e) {
      if (e.key === "ArrowDown") { e.preventDefault(); this.$refs.list.focus(); this.move(Math.max(this.active, 0)); }
      else if (e.key === "Enter") { e.preventDefault(); this.$refs.list.focus(); this.move(Math.max(this.active, 0)); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); this.close(true); }
    },
    onListFocus() { if (this.active < 0 && this.shown.length) this.active = 0; },
    onListKey(e) {
      const k = e.key;
      if (k === "ArrowDown") { e.preventDefault(); this.move(this.active + 1); }
      else if (k === "ArrowUp") {
        e.preventDefault();
        if (this.active <= 0) { this.active = -1; this.$refs.search.focus(); } else this.move(this.active - 1);
      } else if (k === "Home") { e.preventDefault(); this.move(0); }
      else if (k === "End") { e.preventDefault(); this.move(this.shown.length - 1); }
      else if (k === " " || k === "Enter") {
        e.preventDefault();
        if (this.shown[this.active]) this.toggleOpt(this.shown[this.active]);
      } else if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "a") { e.preventDefault(); this.setAll(true); }
      else if (k === "Escape") { e.preventDefault(); e.stopPropagation(); this.close(true); }
      else if (k.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {  // gõ chữ: quay về ô tìm
        this.$refs.search.focus();
      }
    },
  },
};
