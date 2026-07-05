interface MSALConfig {
    auth: {
        clientId: string,
        authority: string,
        redirectUri: string,
        scope: string
    },
    cache: {
        cacheLocation: string,
        storeAuthStateInCookie: boolean,
    }
}

interface APIConfig {
    MSALConfig: MSALConfig
}
let config = {
    MSALConfig: {
        auth: {
            clientId: '2e82f259-2042-4fe7-861e-5b214bf65acb',
            authority: 'https://login.microsoftonline.com/03d87c9e-bf69-4287-adc9-db61022cf75b',
            // 回跳地址取当前源（需在 Azure 应用注册的 SPA 重定向 URI 中登记，如 https://localhost:55876/）
            redirectUri: window.location.origin + '/',
            scope: "access_as_user"
        },
        cache: {
            cacheLocation: "sessionStorage",
            storeAuthStateInCookie: true,
        }
    }
};

export { config }
export type { APIConfig, MSALConfig }