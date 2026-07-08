import fs from 'fs';
import path from 'path';

export interface StackState {
  skipUnindexed: boolean;
  table: string;
}

const STATE_PATH = path.join(__dirname, '..', 'stack-state.json');

export function writeStackState(state: StackState): void {
  fs.writeFileSync(STATE_PATH, JSON.stringify(state, null, 2));
}

export function readStackState(): StackState {
  if (!fs.existsSync(STATE_PATH)) {
    return { skipUnindexed: false, table: 'unknown' };
  }
  return JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')) as StackState;
}
