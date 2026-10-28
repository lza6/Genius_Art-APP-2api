'use strict';
// RPC bridge to app's libamg.so crypto
function doEncrypt(plain, key) {
    var r = null;
    Java.perform(function () {
        var AMG = Java.use('com.android.amg.AMGUtil');
        var ctx = Java.use('android.app.ActivityThread').currentApplication();
        r = AMG.encrypt(ctx, plain, key);
    });
    return r;
}
function doDecrypt(cipher) {
    var r = null;
    Java.perform(function () {
        var AMG = Java.use('com.android.amg.AMGUtil');
        var ctx = Java.use('android.app.ActivityThread').currentApplication();
        r = AMG.decrypt(ctx, cipher);
    });
    return r;
}
function doGetToken(key) {
    var r = null;
    Java.perform(function () {
        var AMG = Java.use('com.android.amg.AMGUtil');
        var ctx = Java.use('android.app.ActivityThread').currentApplication();
        r = AMG.getToken(ctx, key);
    });
    return r;
}
rpc.exports = {
    encrypt: doEncrypt,
    decrypt: doDecrypt,
    gettoken: doGetToken
};
console.log('[*] rpc bridge loaded');
