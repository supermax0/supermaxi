/* Explicit tutorial runtime state machine (no boolean spaghetti). */

export const STATES = Object.freeze({
  IDLE: "IDLE",
  STARTING: "STARTING",
  RUNNING: "RUNNING",
  WAITING_FOR_USER: "WAITING_FOR_USER",
  VALIDATING: "VALIDATING",
  PAUSED: "PAUSED",
  COMPLETED: "COMPLETED",
  FAILED: "FAILED",
  CANCELLED: "CANCELLED",
});

const S = STATES;
const TERMINAL = [S.COMPLETED, S.FAILED, S.CANCELLED];
const ACTIVE_EXITS = { pause: S.PAUSED, fail: S.FAILED, cancel: S.CANCELLED };

export const TRANSITIONS = Object.freeze({
  [S.IDLE]: { start: S.STARTING },
  [S.STARTING]: { ready: S.RUNNING, fail: S.FAILED, cancel: S.CANCELLED },
  [S.RUNNING]: { await: S.WAITING_FOR_USER, validate: S.VALIDATING, advance: S.RUNNING, finish: S.COMPLETED, ...ACTIVE_EXITS },
  [S.WAITING_FOR_USER]: { satisfied: S.RUNNING, validate: S.VALIDATING, ...ACTIVE_EXITS },
  [S.VALIDATING]: { valid: S.RUNNING, invalid: S.WAITING_FOR_USER, finish: S.COMPLETED, ...ACTIVE_EXITS },
  [S.PAUSED]: { resume: S.RUNNING, fail: S.FAILED, cancel: S.CANCELLED },
  [S.COMPLETED]: { reset: S.IDLE },
  [S.FAILED]: { reset: S.IDLE },
  [S.CANCELLED]: { reset: S.IDLE },
});

export class InvalidTransition extends Error {
  constructor(state, event) {
    super(`Invalid tutorial transition: ${event} from ${state}`);
    this.name = "InvalidTransition";
  }
}

export class TutorStateMachine {
  constructor() {
    this.state = S.IDLE;
    this.listeners = new Set();
  }

  isTerminal() {
    return TERMINAL.includes(this.state);
  }

  can(event) {
    return Object.prototype.hasOwnProperty.call(TRANSITIONS[this.state], event);
  }

  send(event) {
    const next = TRANSITIONS[this.state][event];
    if (next === undefined) throw new InvalidTransition(this.state, event);
    const previous = this.state;
    this.state = next;
    this.listeners.forEach((listener) => listener({ from: previous, to: next, event }));
    return next;
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
