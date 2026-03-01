import type { StateCreator } from 'zustand';
import type { ConnectionState } from '../../data/types';
import type { AppStore } from '../app-store';

export interface ConnectionSlice {
  connectionState: ConnectionState;
  lastHeartbeat: number;
  setConnectionState: (state: ConnectionState) => void;
  setLastHeartbeat: (ts: number) => void;
}

export const createConnectionSlice: StateCreator<
  AppStore,
  [['zustand/devtools', never], ['zustand/persist', unknown], ['zustand/immer', never]],
  [],
  ConnectionSlice
> = (set) => ({
  connectionState: 'disconnected',
  lastHeartbeat: 0,

  setConnectionState: (state) =>
    set(
      (draft) => {
        draft.connectionState = state;
      },
      false,
      'connection/setState',
    ),

  setLastHeartbeat: (ts) =>
    set(
      (draft) => {
        draft.lastHeartbeat = ts;
      },
      false,
      'connection/setHeartbeat',
    ),
});
