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
      <!-- nền mờ phía sau khi mở thao tác nhanh: tách các nút khỏi giao diện bên dưới; bấm vào nền để đóng -->
      <div v-if="open || ctx" class="sr-fab-scrim" aria-hidden="true" @click="open ? closeDial(false) : (ctx = null)"></div>
      <button v-if="actions.length" ref="fab" type="button" class="sr-fab" :class="{ open: open }"
              :aria-expanded="open ? 'true' : 'false'" :aria-controls="open ? dialId : null"
              :aria-label="open ? 'Đóng thao tác nhanh' : fabLabel" @click="toggle">
        <q-icon name="add" size="28px" aria-hidden="true" />
      </button>
      <!-- nút +: các thao tác xếp trên cung tròn phía trên-trái (góc màn hình), nhãn hiện khi rê / focus -->
      <div v-if="open" :id="dialId" class="sr-radial arc" role="menu" :aria-label="fabLabel"
           @keydown="navKey($event, btns)">
        <button v-for="(a, i) in actions" :key="a.key" :ref="el => (btns[i] = el)" type="button" role="menuitem"
                class="sr-rad-item" :style="arcPos(i)" :aria-label="a.label + (a.badge ? ' · ' + a.badge : '')"
                @click="pick(a)">
          <q-icon :name="a.icon" size="22px" aria-hidden="true" />
          <span class="sr-rad-label left">{{ a.label }}<span v-if="a.badge" class="sr-fab-count"> · {{ a.badge }}</span></span>
        </button>
      </div>
      <!-- chuột phải: vòng tròn thao tác quanh con trỏ, nút đóng ở giữa -->
      <div v-if="ctx" class="sr-radial ring" role="menu" :aria-label="fabLabel"
           :style="{ left: ctx.x + 'px', top: ctx.y + 'px' }" @contextmenu.prevent @keydown="navKey($event, ctxBtns)">
        <button type="button" class="sr-rad-center" aria-label="Đóng" @click="ctx = null">
          <q-icon name="close" size="18px" aria-hidden="true" /></button>
        <button v-for="(a, i) in actions" :key="a.key" :ref="el => (ctxBtns[i] = el)" type="button" role="menuitem"
                class="sr-rad-item" :style="ringPos(i)" :aria-label="a.label + (a.badge ? ' · ' + a.badge : '')"
                @click="pickCtx(a)">
          <q-icon :name="a.icon" size="22px" aria-hidden="true" />
          <span class="sr-rad-label" :class="ringSide(i)">{{ a.label }}<span v-if="a.badge" class="sr-fab-count">
            · {{ a.badge }}</span></span>
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
    actions: { type: Array, default: () => [] },  // [{key, icon, label, badge?}] — tối đa 5 thao tác
    fabLabel: { type: String, default: "Thao tác nhanh" },
    chat: { type: Object, default: null },        // {label, icon} — nút chat / hỗ trợ xếp chung cột
    topAfter: { type: Number, default: 400 },
  },
  emits: ["action", "chat"],
  data() { return { open: false, showTop: false, dialId: `sr-fab-${++uid}-dial`, btns: [], ctxBtns: [], ctx: null }; },
  mounted() {
    this.onScroll = () => { this.showTop = window.scrollY > this.topAfter; this.ctx = null; };
    this.onDown = (e) => {
      if (this.open && this.$refs.root && !this.$refs.root.contains(e.target)) this.closeDial(false);
      if (this.ctx && !(e.target.closest && e.target.closest(".sr-radial.ring"))) this.ctx = null;
    };
    // Chuột phải: thay menu của trình duyệt bằng các thao tác của tool (ô nhập liệu vẫn giữ menu sao chép / dán).
    this.onCtx = (e) => {
      if (!this.actions.length || (e.target.closest && e.target.closest("input, textarea, select, [contenteditable]"))) return;
      e.preventDefault();
      this.closeDial(false);
      const m = this.ringR + 34;  // vòng không tràn khỏi màn hình
      this.ctx = { x: Math.max(m, Math.min(e.clientX, window.innerWidth - m)),
                   y: Math.max(m, Math.min(e.clientY, window.innerHeight - m)) };
      this.$nextTick(() => this.ctxBtns[0] && this.ctxBtns[0].focus());
    };
    this.onEsc = (e) => { if (e.key === "Escape") this.ctx = null; };
    window.addEventListener("scroll", this.onScroll, { passive: true });
    document.addEventListener("mousedown", this.onDown);
    document.addEventListener("contextmenu", this.onCtx);
    document.addEventListener("keydown", this.onEsc);
    document.body.classList.add("sr-has-fab");  // chừa khoảng trống dưới trang (CSS) để nút không che nội dung
    this.onScroll();
  },
  unmounted() {
    window.removeEventListener("scroll", this.onScroll);
    document.removeEventListener("mousedown", this.onDown);
    document.removeEventListener("contextmenu", this.onCtx);
    document.removeEventListener("keydown", this.onEsc);
    document.body.classList.remove("sr-has-fab");
  },
  computed: {
    ringR() { return this.actions.length > 6 ? 92 : 78; },    // bán kính vòng chuột phải
  },
  methods: {
    // vị trí của thao tác thứ i trong cột phía trên nút +
    arcPos(i) {
      // một cột thẳng phía trên nút +, mục đầu gần nút + nhất; nhãn luôn hiện bên trái
      const gap = this.actions.length > 6 ? 54 : 58;
      return { left: '0px', top: -(66 + i * gap) + 'px', animationDelay: (i * 25) + 'ms' };
    },
    // vị trí trên vòng tròn quanh con trỏ, mục đầu ở trên cùng, theo chiều kim đồng hồ
    ringPos(i) {
      const n = this.actions.length, rad = (-90 + 360 * i / n) * Math.PI / 180, r = this.ringR;
      return { left: (r * Math.cos(rad)) + 'px', top: (r * Math.sin(rad)) + 'px', animationDelay: (i * 20) + 'ms' };
    },
    ringSide(i) {
      const x = Math.cos((-90 + 360 * i / this.actions.length) * Math.PI / 180);
      return Math.abs(x) < 0.2 ? 'top' : (x < 0 ? 'left' : 'right');
    },
    // phím mũi tên: chuyển qua lại giữa các thao tác trên vòng
    navKey(e, list) {
      const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
      if (!(e.key in keys)) return;
      e.preventDefault();
      const items = list.filter(Boolean), i = items.indexOf(document.activeElement);
      const next = items[(i + keys[e.key] + items.length) % items.length];
      if (next) next.focus();
    },
    toggle(e) {
      if (this.open) this.closeDial(true);
      else {
        this.open = true;
        // chỉ khi mở bằng bàn phím (Enter / Space: e.detail = 0) mới đưa focus tới thao tác đầu; bấm chuột thì không
        if (e && e.detail === 0) this.$nextTick(() => this.btns[0] && this.btns[0].focus());
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
    pickCtx(a) {
      this.ctx = null;
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
