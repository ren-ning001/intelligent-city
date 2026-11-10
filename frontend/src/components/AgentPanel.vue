<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import {
  Bot,
  Check,
  CircleAlert,
  CornerDownLeft,
  Cpu,
  Database,
  History,
  LoaderCircle,
  MapPin,
  MessageSquarePlus,
  Radio,
  Route,
  Search,
  Sparkles,
} from 'lucide-vue-next'
import type { AgentTrace, ChatMessage, ConversationSummary } from '../types'
import MarkdownContent from './MarkdownContent.vue'

const props = defineProps<{
  messages: ChatMessage[]
  steps: AgentTrace[]
  sessions: ConversationSummary[]
  currentSessionId: string
  thinking: boolean
  configured: boolean
}>()

const emit = defineEmits<{
  send: [message: string]
  newChat: []
  selectSession: [sessionId: string]
}>()

const input = ref('')
const historyOpen = ref(false)
const messageList = ref<HTMLDivElement>()
const suggestions = [
  '规划一条经过公园的西湖步行路线',
  '帮我找附近的酒店和历史景点',
  '解释当前路线为什么这样走',
]

function traceIcon(tool: string) {
  if (tool === 'geocode_location') return MapPin
  if (tool === 'search_tourism_pois') return Search
  if (tool === 'prepare_osm_region') return Database
  if (
    tool === 'plan_walking_route'
    || tool === 'publish_tourism_itinerary'
  ) return Route
  return Cpu
}

function send(value = input.value) {
  const message = value.trim()
  if (!message || props.thinking) return
  emit('send', message)
  input.value = ''
}

function selectSession(sessionId: string) {
  historyOpen.value = false
  emit('selectSession', sessionId)
}

function newConversation() {
  historyOpen.value = false
  emit('newChat')
}

function formatSessionTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

watch(
  () => [props.messages.length, props.steps.length, props.thinking],
  async () => {
    await nextTick()
    messageList.value?.scrollTo({
      top: messageList.value.scrollHeight,
      behavior: 'smooth',
    })
  },
)
</script>

<template>
  <section class="glass-panel agent-panel">
    <header class="agent-header">
      <div class="agent-avatar">
        <Bot :size="21" />
        <span />
      </div>
      <div>
        <div class="agent-name">YourRoad Agent</div>
        <div class="agent-meta">
          <Radio :size="11" />
          {{ configured ? 'DeepSeek · DSH工具在线' : '等待DeepSeek密钥' }}
        </div>
      </div>
      <div class="agent-actions">
        <div class="agent-badge">
          <Cpu :size="13" />
          DSH
        </div>
        <button
          type="button"
          class="agent-action"
          title="新建对话"
          aria-label="新建对话"
          :disabled="thinking"
          @click="newConversation"
        >
          <MessageSquarePlus :size="15" />
        </button>
        <div class="history-control">
          <button
            type="button"
            class="agent-action"
            title="历史对话"
            aria-label="历史对话"
            @click="historyOpen = !historyOpen"
          >
            <History :size="15" />
          </button>
        </div>
      </div>
    </header>

    <div v-if="historyOpen" class="history-menu">
      <div class="history-menu__title">
        <History :size="13" />
        历史对话
      </div>
      <button
        v-for="session in sessions"
        :key="session.session_id"
        type="button"
        class="history-item"
        :class="{ active: session.session_id === currentSessionId }"
        :disabled="thinking"
        @click="selectSession(session.session_id)"
      >
        <span class="history-item__title">{{ session.title }}</span>
        <span class="history-item__meta">
          {{ session.message_count }} 条 · {{ formatSessionTime(session.updated_at) }}
        </span>
      </button>
      <div v-if="!sessions.length" class="history-empty">
        发送第一条消息后，对话会自动保存在本地。
      </div>
    </div>

    <div ref="messageList" class="message-list">
      <div
        v-for="message in messages"
        :key="message.id"
        class="message"
        :class="[`message--${message.role}`, { pending: message.pending }]"
      >
        <div v-if="message.role === 'agent'" class="message-icon">
          <Sparkles :size="12" />
        </div>
        <div class="message-bubble">
          <MarkdownContent
            v-if="message.role === 'agent'"
            :content="message.content"
          />
          <template v-else>{{ message.content }}</template>
        </div>
      </div>

      <div v-if="steps.length" class="agent-trace">
        <div class="agent-trace__heading">
          <span>可审计执行过程</span>
          <small>展示工具调用，不展示隐藏思维链</small>
        </div>
        <div
          v-for="step in steps"
          :key="step.id"
          class="trace-step"
          :class="`trace-step--${step.status}`"
        >
          <div class="trace-step__icon">
            <component :is="traceIcon(step.tool)" :size="13" />
          </div>
          <div class="trace-step__content">
            <strong>{{ step.title }}</strong>
            <small>{{ step.detail }}</small>
          </div>
          <LoaderCircle v-if="step.status === 'running'" class="trace-step__state spin" :size="13" />
          <Check v-else-if="step.status === 'completed'" class="trace-step__state" :size="13" />
          <CircleAlert v-else class="trace-step__state" :size="13" />
        </div>
      </div>

      <div v-if="thinking" class="thinking-row">
        <span /><span /><span />
        <em>正在调用真实地图工具</em>
      </div>
    </div>

    <div v-if="messages.length < 3" class="suggestions">
      <button
        v-for="suggestion in suggestions"
        :key="suggestion"
        type="button"
        @click="send(suggestion)"
      >
        {{ suggestion }}
      </button>
    </div>

    <form class="agent-input" @submit.prevent="send()">
      <textarea
        v-model="input"
        rows="1"
        placeholder="描述你的旅行愿望与限制…"
        @keydown.enter.exact.prevent="send()"
      />
      <button type="submit" :disabled="thinking || !input.trim()" aria-label="发送">
        <CornerDownLeft :size="17" />
      </button>
    </form>
    <div class="agent-disclaimer">
      路线与距离由OSM确定性工具计算，Agent不直接编造地图事实
    </div>
  </section>
</template>

<style scoped>
.agent-panel {
  position: relative;
  display: flex;
  width: 100%;
  height: 100%;
  flex-direction: column;
  overflow: hidden;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  backdrop-filter: none;
}

.agent-header {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 17px 18px;
  border-bottom: 1px solid rgba(77, 107, 254, 0.12);
  background: linear-gradient(90deg, rgba(77, 107, 254, 0.08), transparent);
}

.agent-avatar {
  position: relative;
  display: grid;
  width: 39px;
  height: 39px;
  place-items: center;
  color: #4262dd;
  border: 1px solid rgba(77, 107, 254, 0.24);
  border-radius: 13px;
  background: rgba(77, 107, 254, 0.1);
}

.agent-avatar span {
  position: absolute;
  right: -2px;
  bottom: -2px;
  width: 8px;
  height: 8px;
  border: 2px solid #f7f9ff;
  border-radius: 50%;
  background: #4d6bfe;
}

.agent-name { color: #1e377b; font-size: 13px; font-weight: 750; }
.agent-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 3px;
  color: rgba(39, 60, 111, 0.48);
  font-size: 9px;
}

.agent-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}

.agent-badge {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 8px;
  color: rgba(49, 76, 165, 0.68);
  border: 1px solid rgba(77, 107, 254, 0.12);
  border-radius: 9px;
  background: rgba(77, 107, 254, 0.055);
  font-size: 9px;
  letter-spacing: 0.1em;
}

.agent-action {
  display: grid;
  width: 29px;
  height: 29px;
  padding: 0;
  place-items: center;
  color: rgba(49, 76, 165, 0.7);
  border: 1px solid rgba(77, 107, 254, 0.13);
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.55);
  transition: 160ms ease;
}

.agent-action:hover:not(:disabled) {
  color: #3657dc;
  border-color: rgba(77, 107, 254, 0.3);
  background: rgba(77, 107, 254, 0.1);
}

.agent-action:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.history-control {
  display: flex;
}

.history-menu {
  position: absolute;
  z-index: 8;
  top: 69px;
  right: 12px;
  width: min(310px, calc(100% - 24px));
  max-height: min(360px, calc(100% - 100px));
  overflow-y: auto;
  padding: 8px;
  border: 1px solid rgba(77, 107, 254, 0.16);
  border-radius: 13px;
  background: rgba(250, 252, 255, 0.97);
  box-shadow: 0 18px 48px rgba(50, 71, 139, 0.2);
  backdrop-filter: blur(16px);
}

.history-menu__title {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 7px 9px;
  color: rgba(30, 55, 123, 0.78);
  font-size: 10px;
  font-weight: 700;
}

.history-item {
  display: block;
  width: 100%;
  padding: 9px 10px;
  text-align: left;
  border: 0;
  border-radius: 9px;
  background: transparent;
}

.history-item:hover:not(:disabled),
.history-item.active {
  background: rgba(77, 107, 254, 0.08);
}

.history-item.active {
  box-shadow: inset 2px 0 #4d6bfe;
}

.history-item__title,
.history-item__meta {
  display: block;
}

.history-item__title {
  overflow: hidden;
  color: rgba(27, 48, 101, 0.86);
  font-size: 10px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-item__meta {
  margin-top: 4px;
  color: rgba(40, 61, 112, 0.42);
  font-size: 8px;
}

.history-empty {
  padding: 18px 12px;
  color: rgba(40, 61, 112, 0.46);
  font-size: 9px;
  line-height: 1.6;
  text-align: center;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 18px;
  scrollbar-color: rgba(77, 107, 254, 0.24) transparent;
}

.message {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 13px;
  animation: message-in 320ms ease both;
}

.message--user { justify-content: flex-end; }
.message-icon {
  display: grid;
  width: 23px;
  height: 23px;
  flex: 0 0 auto;
  place-items: center;
  color: #4d6bfe;
  border-radius: 8px;
  background: rgba(77, 107, 254, 0.1);
}

.message-bubble {
  min-width: 0;
  max-width: 82%;
  padding: 10px 12px;
  color: rgba(26, 46, 93, 0.82);
  border: 1px solid rgba(77, 107, 254, 0.1);
  border-radius: 4px 14px 14px 14px;
  background: rgba(77, 107, 254, 0.045);
  font-size: 12px;
  line-height: 1.58;
  white-space: pre-wrap;
}

.message--agent .message-bubble {
  width: calc(100% - 31px);
  max-width: none;
  white-space: normal;
}

.message--user .message-bubble {
  color: #fff;
  border: 0;
  border-radius: 14px 4px 14px 14px;
  background: linear-gradient(135deg, #4d6bfe, #7c98ff);
  font-weight: 600;
}

.message--system .message-bubble {
  max-width: 100%;
  color: #ffdca0;
  border-color: rgba(255, 202, 115, 0.17);
  background: rgba(92, 62, 19, 0.18);
}

.thinking-row {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 31px;
  color: rgba(38, 59, 109, 0.5);
}

.agent-trace {
  margin: 8px 0 14px 31px;
  padding: 10px;
  border: 1px solid rgba(130, 164, 255, 0.18);
  border-radius: 12px;
  background: rgba(31, 57, 125, 0.12);
}

.agent-trace__heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.agent-trace__heading span {
  color: rgba(29, 48, 96, 0.8);
  font-size: 10px;
  font-weight: 700;
}

.agent-trace__heading small {
  color: rgba(40, 61, 112, 0.4);
  font-size: 7px;
}

.trace-step {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 0;
  border-top: 1px solid rgba(153, 180, 255, 0.08);
}

.trace-step__icon {
  display: grid;
  width: 23px;
  height: 23px;
  flex: 0 0 auto;
  place-items: center;
  color: #9cb2ff;
  border-radius: 7px;
  background: rgba(88, 117, 241, 0.13);
}

.trace-step__content {
  min-width: 0;
  flex: 1;
}

.trace-step__content strong,
.trace-step__content small {
  display: block;
}

.trace-step__content strong {
  color: rgba(29, 48, 96, 0.78);
  font-size: 9px;
}

.trace-step__content small {
  margin-top: 3px;
  color: rgba(40, 61, 112, 0.48);
  font-size: 8px;
  line-height: 1.45;
}

.trace-step__state {
  flex: 0 0 auto;
  margin-top: 5px;
  color: #86a2ff;
}

.trace-step--completed .trace-step__state { color: #70d6b2; }
.trace-step--failed .trace-step__state { color: #ff9d9d; }
.spin { animation: spin 0.9s linear infinite; }

.thinking-row span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #4d6bfe;
  animation: typing 1.2s infinite;
}
.thinking-row span:nth-child(2) { animation-delay: 0.15s; }
.thinking-row span:nth-child(3) { animation-delay: 0.3s; }
.thinking-row em {
  margin-left: 4px;
  font-size: 9px;
  font-style: normal;
  letter-spacing: 0.04em;
}

.suggestions {
  display: flex;
  gap: 7px;
  overflow-x: auto;
  padding: 0 17px 12px;
  scrollbar-width: none;
}

.suggestions button {
  flex: 0 0 auto;
  padding: 7px 10px;
  color: rgba(38, 59, 109, 0.56);
  border: 1px solid rgba(77, 107, 254, 0.12);
  border-radius: 999px;
  background: rgba(77, 107, 254, 0.05);
  font-size: 9px;
}

.agent-input {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  margin: 0 16px;
  padding: 9px 9px 9px 12px;
  border: 1px solid rgba(77, 107, 254, 0.16);
  border-radius: 15px;
  background: rgba(255, 255, 255, 0.78);
  transition: 180ms ease;
}

.agent-input:focus-within {
  border-color: rgba(77, 107, 254, 0.38);
  box-shadow: 0 0 0 3px rgba(77, 107, 254, 0.07);
}

.agent-input textarea {
  width: 100%;
  max-height: 92px;
  resize: none;
  border: 0;
  outline: 0;
  color: var(--text);
  background: transparent;
  font: inherit;
  font-size: 12px;
  line-height: 1.5;
}

.agent-input textarea::placeholder { color: rgba(41, 62, 113, 0.34); }
.agent-input button {
  display: grid;
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  place-items: center;
  color: #fff;
  border: 0;
  border-radius: 10px;
  background: #4d6bfe;
}
.agent-input button:disabled { opacity: 0.25; }

.agent-disclaimer {
  padding: 8px 18px 13px;
  color: rgba(40, 61, 112, 0.38);
  font-size: 8px;
  text-align: center;
}

@keyframes typing {
  0%, 70%, 100% { transform: translateY(0); opacity: 0.32; }
  35% { transform: translateY(-4px); opacity: 1; }
}
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes message-in {
  from { transform: translateY(7px); opacity: 0; }
}

@media (max-width: 760px) {
  .agent-panel {
    width: 100%;
    height: 100%;
  }
}
</style>
