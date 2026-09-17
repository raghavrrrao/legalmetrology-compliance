// React Native ships FormData.js without a declaration file. Only the test
// that reproduces the on-device multipart encoding imports it directly.
declare module 'react-native/Libraries/Network/FormData' {
  const FormData: new () => globalThis.FormData;
  export default FormData;
}
