import type { StateCreator } from 'zustand';
import type { PermissionRequest } from '../../data/types';
import type { PermissionRequestEvent } from '../../data/wire-types';
import { mapPermissionRequest } from '../../api/mappers';
import type { AppStore } from '../app-store';

export interface PermissionSlice {
  permissionQueue: PermissionRequest[];
  pushPermission: (wireEvent: PermissionRequestEvent) => void;
  removePermission: (requestId: string) => void;
  setPermissionQueue: (queue: PermissionRequest[]) => void;
}

export const createPermissionSlice: StateCreator<
  AppStore,
  [['zustand/devtools', never], ['zustand/persist', unknown], ['zustand/immer', never]],
  [],
  PermissionSlice
> = (set) => ({
  permissionQueue: [],

  pushPermission: (wireEvent) =>
    set(
      (draft) => {
        draft.permissionQueue.push(mapPermissionRequest(wireEvent));
      },
      false,
      'permission/push',
    ),

  removePermission: (requestId) =>
    set(
      (draft) => {
        draft.permissionQueue = draft.permissionQueue.filter((p) => p.id !== requestId);
      },
      false,
      'permission/remove',
    ),

  setPermissionQueue: (queue) =>
    set(
      (draft) => {
        draft.permissionQueue = queue;
      },
      false,
      'permission/setQueue',
    ),
});
