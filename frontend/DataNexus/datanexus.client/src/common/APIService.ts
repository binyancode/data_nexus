import { API, APIEvent } from './API.js';

import { ElNotification, ElMessage, ElMessageBox, ElLoading } from 'element-plus'
const service = new API();

service.on(APIEvent.TokenExpired)
  .then(async ({ api, response }) => {
    ElMessage({
      message: 'The login token has expired. Please log in again.',
      grouping: true,
      type: 'warning',
      duration: 0,
      showClose: true
    });
  }).all();

service.on(APIEvent.Authenticate)
  .then(async ({ api, response }) => {
    ElMessage({
      message: 'Login success.',
      type: 'success'
    });
  })
  .catch(async ({ api, err }) => {
    ElMessage({
      message: 'Transferring to the login page...',
      type: 'warning',
      duration: 10000
    });
  }).all();


service.on(APIEvent.Autherize)
  .then(async ({ api, response }) => {
    ElMessage({
      message: 'Autherization success.',
      type: 'success',
      duration: 5000
    })
  })
  .catch(async ({ api, err }) => {
    ElMessage({
      message: 'Autheriaztion failed, please refresh and try again.',
      type: 'error',
      duration: 0,
      showClose: true
    });
  }).all();

service.on(APIEvent.Request)
  .then(async ({ api, response }) => {
    if (response.data.message != null || response.data.message != "") {
      if (response.data.message) {
        ElMessage({
          message: response.data.message,
          type: 'info',
          grouping: true,
          duration: 5000
        });
      }
    }
  })
  .catch(({ api, err }) => {
    ElMessage({
      message: `${api}, ${err.message}`,
      type: 'error',
      grouping: true,
      duration: 10000,
      showClose: true
    });
  }).all();

export { service }
