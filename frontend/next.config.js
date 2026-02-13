/** @type {import('next').NextConfig} */

const isCloudBuild = !!process.env.NEXT_PUBLIC_API_URL;

const nextConfig = {
  output: isCloudBuild ? 'export' : 'standalone',
  images: {
    remotePatterns: [
      {
        protocol: 'http',
        hostname: 'localhost',
        port: '8000',
        pathname: '/api/images/**',
      },
      {
        protocol: 'https',
        hostname: '*.blob.core.windows.net',
        pathname: '/**',
      },
      {
        protocol: 'https',
        hostname: '*.azurecontainerapps.io',
        pathname: '/api/**',
      },
    ],
    unoptimized: true,
  },
  ...(isCloudBuild
    ? {}
    : {
        async rewrites() {
          return [
            {
              source: '/api/:path*',
              destination: `${process.env.INTERNAL_API_URL || 'http://localhost:8000'}/api/:path*`,
            },
          ];
        },
      }),
};

module.exports = nextConfig;
