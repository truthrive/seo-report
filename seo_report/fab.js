// Nhóm nút nổi góc dưới phải (một cột, tương đương FloatButton.Group):
//   dưới cùng: nút tròn màu nhấn có dấu + (FloatingActionButton / Fab) mở speed dial 3 thao tác nhỏ có nhãn
//   trên đó: nút chat (nếu có), rồi nút về đầu trang — chỉ hiện khi đã cuộn quá 400px (FloatButton.BackTop)
// Cả cột đặt trên env(safe-area-inset-bottom); trang được chừa khoảng trống dưới cùng để nút không che nội dung.
// Speed dial là nút disclosure: aria-expanded + aria-controls; các thao tác là nút thường có nhãn hiện sẵn.
// Escape hoặc bấm ra ngoài thì đóng, focus quay về nút +.
let uid = 0;

export default {
  template: `
    <div class="sr-fab-group" ref="root" @keydown.esc="closeDial(true)">
      <button v-if="actions.length" ref="fab" type="button" class="sr-fab" :class="{ open: open }"
              :aria-expanded="open ? 'true' : 'false'" :aria-controls="open ? dialId : null"
              :aria-label="open ? 'Đóng thao tác nhanh' : fabLabel" @click="toggle">
        <q-icon name="add" size="28px" aria-hidden="true" />
      </button>
      <div v-if="open" :id="dialId" class="sr-fab-dial" role="group" :aria-label="fabLabel">
        <button v-for="(a, i) in actions" :key="a.key" :ref="el => (btns[i] = el)" type="button" class="sr-fab-action"
                :style="{ transitionDelay: (i * 30) + 'ms' }" @click="pick(a)">
          <span class="sr-fab-label">{{ a.label }}<span v-if="a.badge" class="sr-fab-count"> · {{ a.badge }}</span></span>
          <span class="sr-fab-mini" aria-hidden="true"><q-icon :name="a.icon" size="20px" /></span>
        </button>
      </div>
      <button v-if="chat" type="button" class="sr-fab-chat" :aria-label="chat.label" @click="$emit('chat')">
        <q-icon :name="chat.icon || 'chat'" size="20px" aria-hidden="true" /><span>{{ chat.label }}</span>
      </button>
      <button type="button" class="sr-fab-top" :class="{ show: showTop }" :tabindex="showTop ? 0 : -1"
              :aria-hidden="showTop ? null : 'true'" aria-label="Về đầu trang" title="Về đầu trang" @click="toTop">
        <q-icon name="arrow_upward" size="20px" aria-hidden="true" />
      </button>
    </div>`,
  props: {
    actions: { type: Array, default: () => [] },  // [{key, icon, label, badge?}] — tối đa 3 thao tác
    fabLabel: { type: String, default: "Thao tác nhanh" },
    chat: { type: Object, default: null },        // {label, icon} — nút chat / hỗ trợ xếp chung cột
    topAfter: { type: Number, default: 400 },
  },
  emits: ["action", "chat"],
  data() { return { open: false, showTop: false, dialId: `sr-fab-${++uid}-dial`, btns: [] }; },
  mounted() {
    this.onScroll = () => { this.showTop = window.scrollY > this.topAfter; };
    this.onDown = (e) => { if (this.open && this.$refs.root && !this.$refs.root.contains(e.target)) this.closeDial(false); };
    window.addEventListener("scroll", this.onScroll, { passive: true });
    document.addEventListener("mousedown", this.onDown);
    document.body.classList.add("sr-has-fab");  // chừa khoảng trống dưới trang (CSS) để nút không che nội dung
    this.onScroll();
  },
  unmounted() {
    window.removeEventListener("scroll", this.onScroll);
    document.removeEventListener("mousedown", this.onDown);
    document.body.classList.remove("sr-has-fab");
  },
  methods: {
    toggle() {
      if (this.open) this.closeDial(true);
      else {
        this.open = true;
        this.$nextTick(() => this.btns[0] && this.btns[0].focus());  // mở bằng bàn phím: đưa focus tới thao tác đầu
      }
    },
    closeDial(returnFocus) {
      if (!this.open) return;
      this.open = false;
      if (returnFocus) this.$nextTick(() => this.$refs.fab && this.$refs.fab.focus());
    },
    pick(a) {
      this.closeDial(false);
      this.$emit("action", a.key);
    },
    toTop() {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
      const main = document.querySelector("main, .q-page");
      if (main) { main.setAttribute("tabindex", "-1"); main.focus({ preventScroll: true }); }
    },
  },
};
